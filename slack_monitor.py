#!/usr/bin/env python3
"""
Slack Monitor — Unreplied Message Alert
========================================
Monitors Slack for DMs from specific people and mentions in specific channels.
If you haven't replied within REPLY_TIMEOUT_MINUTES, it sends you a WhatsApp
message AND makes a phone call via Twilio.

Configuration is via environment variables (see .env.example).
For local dev, copy .env.example to .env and fill in your values.
For Railway/Render, set the variables in the platform dashboard.
"""

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from twilio.rest import Client

load_dotenv()  # loads .env if present (no-op in production where vars are set directly)

# ===========================================================================
# CONFIGURATION — Set via environment variables
# ===========================================================================

# --- Slack ---
# Bot token (xoxb-...) — used for channel @mention scanning. The bot must be
# invited to each channel listed in MONITORED_CHANNELS.
SLACK_BOT_TOKEN  = os.environ["SLACK_BOT_TOKEN"]

# OPTIONAL user token (xoxp-...) — required if you want to monitor DMs *to you*
# from MONITORED_PEOPLE. A bot token cannot see your personal DMs; it only sees
# DMs sent to the bot itself. Generate this from your Slack app's
# "OAuth & Permissions" page under "User Token Scopes":
#   im:history, im:read, mpim:history, users:read
# If left blank, DM monitoring is skipped (only @mentions are watched).
SLACK_USER_TOKEN = os.environ.get("SLACK_USER_TOKEN", "").strip()

MY_SLACK_USER_ID = os.environ["MY_SLACK_USER_ID"]

# Comma-separated Slack User IDs whose DMs should trigger alerts
# e.g. MONITORED_PEOPLE=U0AAA1,U0BBB2
MONITORED_PEOPLE = [
    uid.strip()
    for uid in os.environ.get("MONITORED_PEOPLE", "").split(",")
    if uid.strip()
]

# Comma-separated Slack Channel IDs to monitor for @mentions
# e.g. MONITORED_CHANNELS=C0AAA1,C0BBB2
MONITORED_CHANNELS = [
    cid.strip()
    for cid in os.environ.get("MONITORED_CHANNELS", "").split(",")
    if cid.strip()
]

# --- Twilio ---
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN  = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

# --- Your contact info ---
YOUR_WHATSAPP_NUMBER = os.environ["YOUR_WHATSAPP_NUMBER"]
YOUR_PHONE_NUMBER    = os.environ["YOUR_PHONE_NUMBER"]

# --- Alert settings (optional, with sensible defaults) ---
REPLY_TIMEOUT_MINUTES = int(os.environ.get("REPLY_TIMEOUT_MINUTES", "5"))
LOOKBACK_MINUTES      = int(os.environ.get("LOOKBACK_MINUTES", "60"))
SEND_WHATSAPP         = os.environ.get("SEND_WHATSAPP", "true").lower() == "true"
SEND_CALL             = os.environ.get("SEND_CALL", "true").lower() == "true"

# Max characters of the original Slack message to include in the WhatsApp body.
# Anything longer is truncated with an ellipsis. Calls always read the short
# alert summary only (long voice messages are unpleasant to listen to).
MAX_TEXT_CHARS = int(os.environ.get("MAX_TEXT_CHARS", "600"))

# State file — tracks messages already alerted on
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_state.json")

# ===========================================================================
# CORE LOGIC — No need to edit below this line
# ===========================================================================

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"pending": {}, "alerted": {}}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


_user_name_cache: dict[str, str] = {}


def get_user_name(slack: WebClient, user_id: str) -> str:
    if not user_id:
        return "(unknown)"
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        info = slack.users_info(user=user_id)
        name = info["user"].get("real_name") or info["user"].get("name") or user_id
    except Exception:
        name = user_id
    _user_name_cache[user_id] = name
    return name


_MENTION_RE = __import__("re").compile(r"<@([A-Z0-9]+)>")
_CHANNEL_RE = __import__("re").compile(r"<#([A-Z0-9]+)\|([^>]*)>")
_LINK_RE    = __import__("re").compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>")


def humanize_slack_text(slack: WebClient, text: str) -> str:
    """Turn raw Slack message text (with <@U123>, <#C123|name>, <url|label>)
    into something readable for WhatsApp / a phone speaker."""
    if not text:
        return ""

    def _user_sub(m):
        return "@" + get_user_name(slack, m.group(1))

    text = _MENTION_RE.sub(_user_sub, text)
    text = _CHANNEL_RE.sub(lambda m: "#" + m.group(2), text)
    text = _LINK_RE.sub(lambda m: m.group(2) if m.group(2) else m.group(1), text)
    # Slack uses HTML-escaped &amp; &lt; &gt; in message text
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text.strip()


def truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def get_channel_name(slack: WebClient, channel_id: str) -> str:
    try:
        info = slack.conversations_info(channel=channel_id)
        return info["channel"].get("name") or channel_id
    except Exception:
        return channel_id


def user_replied_after(slack: WebClient, channel_id: str, msg_ts: str) -> bool:
    """Check whether MY_SLACK_USER_ID sent any message in channel after msg_ts.

    For DM channels, `slack` should be the user-token client so it can see
    the conversation between you and the other person. For public/private
    channels, the bot client is fine as long as the bot is a member."""
    try:
        result = slack.conversations_history(
            channel=channel_id,
            oldest=msg_ts,
            limit=30,
        )
        for msg in result.get("messages", []):
            ts = msg.get("ts", "0")
            if msg.get("user") == MY_SLACK_USER_ID and float(ts) > float(msg_ts):
                return True
        # Also check thread replies on that specific message
        try:
            replies = slack.conversations_replies(
                channel=channel_id,
                ts=msg_ts,
                oldest=msg_ts,
                limit=20,
            )
            for msg in replies.get("messages", []):
                ts = msg.get("ts", "0")
                if msg.get("user") == MY_SLACK_USER_ID and float(ts) > float(msg_ts):
                    return True
        except SlackApiError:
            pass
    except SlackApiError as e:
        print(f"  [warn] Could not fetch history for {channel_id}: {e}")
    return False


def send_whatsapp_alert(twilio: Client, message: str):
    """Send a WhatsApp message via Twilio sandbox or WhatsApp Business."""
    try:
        twilio.messages.create(
            from_=f"whatsapp:{TWILIO_FROM_NUMBER}",
            to=f"whatsapp:{YOUR_WHATSAPP_NUMBER}",
            body=message,
        )
        print(f"  [✓] WhatsApp sent: {message}")
    except Exception as e:
        print(f"  [✗] WhatsApp failed: {e}")


def send_call_alert(twilio: Client, message: str):
    """Make a phone call via Twilio that reads the message aloud."""
    try:
        safe_msg = message.replace("&", "and").replace("<", "").replace(">", "")
        twiml = f"<Response><Say voice='alice'>{safe_msg}</Say><Pause length='1'/><Say voice='alice'>{safe_msg}</Say></Response>"
        twilio.calls.create(
            twiml=twiml,
            to=YOUR_PHONE_NUMBER,
            from_=TWILIO_FROM_NUMBER,
        )
        print(f"  [✓] Call triggered: {message}")
    except Exception as e:
        print(f"  [✗] Call failed: {e}")


def fire_alerts(twilio: Client, summary: str, whatsapp_body: str | None = None):
    """summary is read aloud on the call; whatsapp_body is what's sent to WhatsApp.
    If whatsapp_body is omitted, it falls back to summary (preserves old behavior)."""
    print(f"\n  ⚠️  ALERT: {summary}")
    if SEND_WHATSAPP:
        send_whatsapp_alert(twilio, whatsapp_body or summary)
    if SEND_CALL:
        send_call_alert(twilio, summary)


def check_pending_and_alert(
    slack_bot: WebClient,
    slack_user: WebClient,
    twilio: Client,
    state: dict,
    now: datetime,
):
    """For every pending message older than REPLY_TIMEOUT_MINUTES, fire alert if no reply.

    Uses the user-token client for DM reply-checks (the bot can't see your DMs)
    and the bot-token client for channel reply-checks."""
    to_alert = []
    for key, info in list(state["pending"].items()):
        msg_ts   = info["ts"]
        channel  = info["channel"]
        sender   = info["sender"]
        msg_type = info["type"]  # "dm" or "mention"

        msg_time    = datetime.fromtimestamp(float(msg_ts))
        age_minutes = (now - msg_time).total_seconds() / 60

        if age_minutes < REPLY_TIMEOUT_MINUTES:
            continue  # Not timed out yet

        # Pick the right client to check whether you've replied
        reply_client = slack_user if msg_type == "dm" else slack_bot
        if user_replied_after(reply_client, channel, msg_ts):
            print(f"  [ok] Already replied to {key}, removing from pending.")
            state["alerted"][key] = state["pending"].pop(key)
            continue

        to_alert.append((key, info, sender, channel, msg_type, int(age_minutes)))

    for key, info, sender, channel, msg_type, age in to_alert:
        # Use bot client for name lookups (users:read on the app is enough)
        sender_name  = get_user_name(slack_bot, sender)
        channel_name = get_channel_name(slack_bot, channel)
        raw_text     = info.get("text", "")  # may be empty for old state entries
        readable     = humanize_slack_text(slack_bot, raw_text)
        body_excerpt = truncate(readable, MAX_TEXT_CHARS) if readable else ""

        if msg_type == "dm":
            summary = (
                f"Slack alert: DM from {sender_name} — "
                f"no reply for {age} minutes!"
            )
        else:
            summary = (
                f"Slack alert: You were mentioned by {sender_name} "
                f"in #{channel_name} — no reply for {age} minutes!"
            )

        # WhatsApp: full alert with the actual message text
        if body_excerpt:
            whatsapp_msg = f"{summary}\n\n💬 {sender_name}: {body_excerpt}"
        else:
            whatsapp_msg = summary

        # Call: short summary only (voice synthesis on long text is rough)
        fire_alerts(twilio, summary=summary, whatsapp_body=whatsapp_msg)
        state["alerted"][key] = state["pending"].pop(key)


def scan_dms(slack: WebClient, state: dict, now: datetime, cutoff_ts: str):
    """Scan DMs from MONITORED_PEOPLE for unread messages.

    `slack` MUST be a user-token client — a bot token cannot see your DMs."""
    if slack is None:
        print("  [skip] No SLACK_USER_TOKEN set, DM monitoring disabled.")
        return
    for person_id in MONITORED_PEOPLE:
        try:
            dm       = slack.conversations_open(users=person_id)
            chan_id  = dm["channel"]["id"]
            history  = slack.conversations_history(channel=chan_id, oldest=cutoff_ts, limit=30)

            for msg in history.get("messages", []):
                sender = msg.get("user", "")
                ts     = msg.get("ts", "")
                text   = msg.get("text", "")
                # Skip our own messages
                if sender == MY_SLACK_USER_ID:
                    continue

                key = f"dm_{chan_id}_{ts}"
                if key not in state["pending"] and key not in state["alerted"]:
                    print(f"  [new] DM from {person_id} at {ts}: {text[:60]!r}")
                    state["pending"][key] = {
                        "ts":       ts,
                        "channel":  chan_id,
                        "sender":   sender,
                        "type":     "dm",
                        "text":     text,
                        "found_at": now.isoformat(),
                    }
        except SlackApiError as e:
            print(f"  [warn] Could not check DMs for {person_id}: {e}")


def scan_mentions(slack: WebClient, state: dict, now: datetime, cutoff_ts: str):
    """Scan MONITORED_CHANNELS for messages that mention MY_SLACK_USER_ID."""
    for channel_id in MONITORED_CHANNELS:
        try:
            history = slack.conversations_history(channel=channel_id, oldest=cutoff_ts, limit=50)

            for msg in history.get("messages", []):
                sender = msg.get("user", "")
                ts     = msg.get("ts", "")
                text   = msg.get("text", "")

                if sender == MY_SLACK_USER_ID:
                    continue
                if f"<@{MY_SLACK_USER_ID}>" not in text:
                    continue

                key = f"mention_{channel_id}_{ts}"
                if key not in state["pending"] and key not in state["alerted"]:
                    print(f"  [new] Mention in {channel_id} at {ts}: {text[:60]!r}")
                    state["pending"][key] = {
                        "ts":       ts,
                        "channel":  channel_id,
                        "sender":   sender,
                        "type":     "mention",
                        "text":     text,
                        "found_at": now.isoformat(),
                    }
        except SlackApiError as e:
            print(f"  [warn] Could not check channel {channel_id}: {e}")


def cleanup_state(state: dict, now: datetime):
    """Remove alerted entries older than 24 hours to keep the state file small."""
    cutoff = (now - timedelta(hours=24)).isoformat()
    before = len(state["alerted"])
    state["alerted"] = {
        k: v for k, v in state["alerted"].items()
        if v.get("found_at", "") >= cutoff
    }
    removed = before - len(state["alerted"])
    if removed:
        print(f"  [cleanup] Removed {removed} old alerted entries.")


def main():
    print(f"\n{'='*50}")
    print(f"Slack Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    slack_bot  = WebClient(token=SLACK_BOT_TOKEN)
    slack_user = WebClient(token=SLACK_USER_TOKEN) if SLACK_USER_TOKEN else None
    if slack_user is None:
        print("  [warn] SLACK_USER_TOKEN is not set — DM monitoring will be skipped.")
        print("         Add a user token (xoxp-...) to .env to monitor DMs to you.")
    elif not SLACK_USER_TOKEN.startswith("xoxp-"):
        print("  [warn] SLACK_USER_TOKEN does NOT start with 'xoxp-'. It looks like a")
        print("         bot token, not a user token. DM monitoring needs a User OAuth")
        print("         Token from your Slack app's OAuth & Permissions page, with")
        print("         scopes: im:history, im:read, mpim:history, users:read.")
        print("         Disabling DM monitoring until a real user token is provided.")
        slack_user = None
    if not SLACK_BOT_TOKEN.startswith("xoxb-"):
        print(f"  [warn] SLACK_BOT_TOKEN does not start with 'xoxb-' (got prefix "
              f"{SLACK_BOT_TOKEN[:5]!r}). Channel mention scanning may fail.")
    twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    state  = load_state()
    now    = datetime.now()
    cutoff = str((now - timedelta(minutes=LOOKBACK_MINUTES)).timestamp())

    print(f"\n[1/4] Scanning DMs from {len(MONITORED_PEOPLE)} monitored people...")
    scan_dms(slack_user, state, now, cutoff)

    print(f"\n[2/4] Scanning {len(MONITORED_CHANNELS)} channels for mentions...")
    scan_mentions(slack_bot, state, now, cutoff)

    print(f"\n[3/4] Checking {len(state['pending'])} pending message(s) for timeout...")
    # If no user token, fall back to bot client for DM reply-checks (will be a no-op).
    check_pending_and_alert(slack_bot, slack_user or slack_bot, twilio, state, now)

    print(f"\n[4/4] Cleaning up old entries...")
    cleanup_state(state, now)

    save_state(state)
    print(f"\nDone. Pending: {len(state['pending'])}  |  Alerted (24h): {len(state['alerted'])}\n")


if __name__ == "__main__":
    main()
