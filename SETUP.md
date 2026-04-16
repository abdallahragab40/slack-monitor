# Slack Monitor — Setup Guide

Sends you a **WhatsApp message** and **phone call** when someone DMs you or mentions you in Slack and you haven't replied within 5 minutes.

---

## Step 1 — Install Dependencies

Open a terminal and run:

```bash
pip install slack-sdk twilio
```

---

## Step 2 — Create a Slack Bot

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it anything (e.g. "My Monitor") and pick your workspace
3. In the left sidebar, go to **OAuth & Permissions**
4. Under **Bot Token Scopes**, add these scopes:
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `im:write`
   - `users:read`
   - `channels:read`
   - `groups:read`
5. Click **Install to Workspace** → Authorize
6. Copy the **Bot OAuth Token** (starts with `xoxb-`)

> ⚠️ Also **invite the bot** to each channel you want to monitor:
> In Slack, open the channel → click the channel name → Integrations → Add an App

---

## Step 3 — Get Your Slack User ID

1. Open Slack → click your profile picture (top right)
2. Click **Profile** → click **⋮ More** → **Copy member ID**
3. It looks like: `U0123ABCDEF`

---

## Step 4 — Get Slack User/Channel IDs to Monitor

**For people:** In Slack, click on their profile → **⋮ More** → **Copy member ID**

**For channels:** Right-click the channel name → **View channel details** → scroll to the bottom to find the Channel ID (starts with `C`)

---

## Step 5 — Set Up Twilio

### For WhatsApp (Sandbox — free to test):

1. Sign in to [console.twilio.com](https://console.twilio.com)
2. Go to **Messaging → Try it out → Send a WhatsApp message**
3. Follow the instructions to join the sandbox (send a WhatsApp message to Twilio's number)
4. Use `+14155238886` as `TWILIO_FROM_NUMBER` for sandbox mode

### For Phone Calls:

1. Go to **Phone Numbers → Manage → Active Numbers**
2. Use any voice-capable Twilio number as `TWILIO_FROM_NUMBER`

### Get your credentials:

- **Account SID** and **Auth Token**: found on your [Twilio Console Dashboard](https://console.twilio.com)

---

## Step 6 — Edit the Script

Open `slack_monitor.py` and fill in the **CONFIGURATION** section at the top:

```python
SLACK_BOT_TOKEN       = "xoxb-..."           # From Step 2
MY_SLACK_USER_ID      = "U0123ABCDEF"         # From Step 3
MONITORED_PEOPLE      = ["U0AAAAAA1", ...]    # From Step 4
MONITORED_CHANNELS    = ["C0CHANNEL1", ...]   # From Step 4
TWILIO_ACCOUNT_SID    = "ACxxx..."            # From Step 5
TWILIO_AUTH_TOKEN     = "your_token"          # From Step 5
TWILIO_FROM_NUMBER    = "+14155238886"        # Twilio sandbox or your number
YOUR_WHATSAPP_NUMBER  = "+201012345678"       # Your WhatsApp (with country code)
YOUR_PHONE_NUMBER     = "+201012345678"       # Your phone for calls
```

---

## Step 7 — Test It

Run the script manually once to confirm it works:

```bash
python3 slack_monitor.py
```

Ask someone to send you a DM or mention you in a monitored channel, wait 5 minutes, and run it again to verify the alert fires.

---

## Step 8 — Run Automatically (every 2 minutes)

```bash
/Users/abdallahragab/Documents/Claude/Projects/slack/venv/bin/python3 /Users/abdallahragab/Documents/Claude/Projects/slack/slack_monitor.py
```

The scheduled task in Cowork handles this automatically. If you prefer to run it manually via cron instead, add this line to your crontab (`crontab -e`):

```
*/2 * * * * python3 /path/to/slack_monitor.py >> /path/to/monitor.log 2>&1
```

---

## Notes

- The script saves state in `monitor_state.json` (same folder) to avoid duplicate alerts
- Alerts are only sent **once per message** — it won't spam you repeatedly
- State entries older than 24 hours are automatically cleaned up
- To change the timeout from 5 minutes, edit `REPLY_TIMEOUT_MINUTES` in the script
- To disable WhatsApp or calls, set `SEND_WHATSAPP = False` or `SEND_CALL = False`
