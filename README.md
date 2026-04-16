# Slack Monitor

Monitors Slack for DMs from specific people and @mentions in specific channels. If you haven't replied within a configurable timeout (default: 5 minutes), it sends you a **WhatsApp message** and makes a **phone call** via Twilio.

Designed to run 24/7 on a cloud host (Railway, Render, Fly.io) and only fires alerts during UK work hours (Mon–Fri, 9 AM–5 PM).

---

## How It Works

```
Every 2 minutes (during work hours):
  1. Scan DMs from monitored people for new messages
  2. Scan monitored channels for @mentions
  3. For any message older than REPLY_TIMEOUT_MINUTES with no reply → fire alert
  4. Clean up state entries older than 24 hours
```

Alerts are fired **once per message** — no spam. State is persisted in `monitor_state.json`.

---

## Project Structure

```
slack-monitor/
├── slack_monitor.py   # Core monitor logic
├── run_loop.py        # Cloud runner (loops every 2 min, work-hours gate)
├── requirements.txt   # Python dependencies
├── Procfile           # Heroku/Railway process declaration
├── railway.toml       # Railway deploy config
├── .env.example       # Environment variable template
└── .gitignore
```

---

## Setup

### 1. Clone & install dependencies

```bash
git clone git@github.com:abdallahragab40/slack-monitor.git
cd slack-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create a Slack Bot

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it (e.g. "My Monitor") and pick your workspace
3. In the sidebar → **OAuth & Permissions** → add these **Bot Token Scopes**:
   - `channels:history`, `groups:history`, `im:history`, `im:write`
   - `users:read`, `channels:read`, `groups:read`
4. Click **Install to Workspace** → Authorize
5. Copy the **Bot OAuth Token** (`xoxb-...`)

> **Important:** Invite the bot to each channel you want to monitor — open the channel in Slack → channel name → Integrations → Add an App.

### 3. Get your Slack IDs

- **Your User ID:** Click your profile picture → Profile → More (⋮) → Copy member ID
- **People to monitor:** Click their profile → More (⋮) → Copy member ID
- **Channels to monitor:** Right-click channel → View channel details → scroll to bottom for the Channel ID (`C...`)

### 4. Set up Twilio

**WhatsApp (sandbox — free for testing):**
1. Sign in to [console.twilio.com](https://console.twilio.com)
2. Go to Messaging → Try it out → Send a WhatsApp message
3. Join the sandbox by sending the shown message to Twilio's WhatsApp number
4. Use `+14155238886` as `TWILIO_FROM_NUMBER`

**Phone calls:** Use any voice-capable number from Phone Numbers → Active Numbers.

Your **Account SID** and **Auth Token** are on the Twilio Console dashboard.

### 5. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your values
```

For local use you can also `export` the variables directly in your shell, or use a tool like `direnv`.

### 6. Test locally

```bash
# Run one check cycle
python3 slack_monitor.py

# Run the full loop (monitors every 2 min during work hours)
python3 run_loop.py
```

---

## Deploy to Railway

1. Push this repo to GitHub (already done if you're reading this)
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
3. Select `slack-monitor`
4. In the project → **Variables** tab, add all variables from `.env.example` with your real values
5. Railway will auto-detect `railway.toml` and start `python run_loop.py`

The service will run continuously and only fire alerts Mon–Fri 9 AM–5 PM UK time.

### Deploy to Render

1. New → Background Worker → connect your GitHub repo
2. Build command: `pip install -r requirements.txt`
3. Start command: `python run_loop.py`
4. Add environment variables in the Render dashboard

### Deploy to Heroku

```bash
heroku create your-app-name
heroku config:set SLACK_BOT_TOKEN=xoxb-... MY_SLACK_USER_ID=U... # etc.
git push heroku main
heroku ps:scale worker=1
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot OAuth token (`xoxb-...`) |
| `MY_SLACK_USER_ID` | Yes | Your Slack user ID |
| `MONITORED_PEOPLE` | Yes | Comma-separated user IDs to watch DMs from |
| `MONITORED_CHANNELS` | Yes | Comma-separated channel IDs to watch for mentions |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio Auth Token |
| `TWILIO_FROM_NUMBER` | Yes | Twilio sender number |
| `YOUR_WHATSAPP_NUMBER` | Yes | Your WhatsApp number (with country code) |
| `YOUR_PHONE_NUMBER` | Yes | Your phone number for calls |
| `REPLY_TIMEOUT_MINUTES` | No | Minutes before alert fires (default: `5`) |
| `LOOKBACK_MINUTES` | No | How far back to scan messages (default: `60`) |
| `SEND_WHATSAPP` | No | Enable WhatsApp alerts (default: `true`) |
| `SEND_CALL` | No | Enable phone call alerts (default: `true`) |

---

## Notes

- `monitor_state.json` is excluded from git — it's runtime state that regenerates automatically
- Alerts fire **once per message** and won't repeat
- State entries older than 24 hours are automatically pruned
- The work-hours gate is in `run_loop.py` and uses the `Europe/London` timezone
- To monitor outside work hours, edit `WORK_START_HR` / `WORK_END_HR` in `run_loop.py`
