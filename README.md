# tg-sgk

`tg-sgk` is a small, bot-only Telegram user automation service designed for OpenClaw.

It logs in with **one Telegram user account** through Telethon, but every API action verifies that the destination entity is a Telegram bot. Human users, groups, and channels are rejected.

## What the MVP supports

- Inspect and verify a Telegram bot target.
- Send text or commands to a bot.
- Read recent bot messages and button layouts.
- Wait for a new message or an edited message.
- Click an inline/reply button by exact text or row/column.
- Save confirmed fixed workflows.
- Run fixed workflows without model reasoning.
- Serialize all Telegram work through one priority queue.
- Give interactive OpenClaw actions priority over queued fixed flows.
- Store basic execution history in SQLite.
- Expose an authenticated HTTP API.
- Serve the API over HTTPS with Caddy.
- Install a companion OpenClaw tool plugin.

## Deliberate limits

The MVP does **not** support:

- Messaging human accounts.
- Sending to groups or channels.
- Multiple Telegram accounts.
- Telegram Mini Apps or external web pages.
- Payments, wallets, CAPTCHA bypass, invitation farming, or mass messaging.
- Server-side scheduling. OpenClaw is expected to trigger scheduled flows.
- Fully autonomous flow repair. OpenClaw can inspect a failed flow and try one operator-approved repair.

## Architecture

```text
OpenClaw
   │ HTTPS + Bearer API key
   ▼
tg-sgk API
   │ single priority worker
   ▼
Telethon user session
   │ bot-only entity verification
   ▼
Third-party Telegram bots
```

The Telegram `.session` file exists only in the persistent `tg_data` service volume. The OpenClaw plugin never receives it.

## Quick local smoke test

The repository includes a deterministic mock Telegram adapter. It exercises the whole API without Telegram credentials.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

export TG_MOCK=true
export TG_SGK_API_KEY=dev-secret-key
export TG_SGK_DATA_DIR="$PWD/data"
export TG_SGK_DATABASE_PATH="$PWD/data/tg-sgk.sqlite3"
export TG_SESSION_PATH="$PWD/data/telegram-user"

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell:

```bash
curl http://127.0.0.1:8000/health

curl -sS http://127.0.0.1:8000/v1/messages/send \
  -H 'Authorization: Bearer dev-secret-key' \
  -H 'Content-Type: application/json' \
  -d '{"bot":"@demo_bot","text":"/start"}'
```

Run checks:

```bash
pytest -q
ruff check app tests
```

## Real Telegram setup

### 1. Get Telegram API credentials

Create an application at `my.telegram.org` and obtain:

- `api_id`
- `api_hash`

Use a dedicated Telegram account for automation when possible.

### 2. Configure the service

```bash
cp .env.example .env
```

Set at least:

```dotenv
TG_SGK_API_KEY=<long random value>
TG_API_ID=<telegram api id>
TG_API_HASH=<telegram api hash>
TG_PHONE=<phone with country code>
TG_SESSION_PATH=/data/telegram-user
TG_MOCK=false
TG_SGK_DOMAIN=tg.example.com
```

Generate an API key:

```bash
openssl rand -hex 32
```

### 3. Create the Telegram session

```bash
docker compose --profile tools run --rm login
```

Telegram will request the login code and, when enabled, the two-step verification password. The resulting session is stored in the Docker named volume `tg_data` and survives container replacement. It must never be copied into the repository.

### 4. Start the HTTPS service

Point `TG_SGK_DOMAIN` to the server, then run:

```bash
docker compose up -d api caddy
```

Caddy obtains and renews the TLS certificate automatically when DNS and ports 80/443 are correctly configured.

Check:

```bash
curl https://tg.example.com/health
```

## API

All `/v1/*` routes require either:

```http
Authorization: Bearer <TG_SGK_API_KEY>
```

or:

```http
X-API-Key: <TG_SGK_API_KEY>
```

### Bot exploration

```text
POST /v1/bots/inspect
POST /v1/messages/send
GET  /v1/messages/recent
POST /v1/messages/wait
POST /v1/buttons/click
```

Every route resolves the target and checks `entity.bot == true` before acting.

### Fixed workflows

```text
POST   /v1/flows
GET    /v1/flows
GET    /v1/flows/{flow_id}
DELETE /v1/flows/{flow_id}
POST   /v1/flows/{flow_id}/run
```

Example:

```json
{
  "id": "example-checkin",
  "name": "Example daily check-in",
  "bot": "@example_bot",
  "steps": [
    { "action": "send_message", "text": "/start" },
    { "action": "wait_message", "timeout_seconds": 20 },
    { "action": "click_button", "text": "每日签到" },
    { "action": "wait_message_or_edit", "timeout_seconds": 20 },
    {
      "action": "assert_text",
      "contains_any": ["签到成功", "今日已签到", "已经签到"]
    }
  ]
}
```

Supported step actions:

- `send_message`
- `wait_message`
- `click_button`
- `wait_message_or_edit`
- `sleep`
- `assert_text`

### History

```text
GET /v1/history?limit=50&target=@example_bot
```

The service stores task type, target, priority, status, result or error, and timestamps. It does not store Telegram credentials.

## Priority behavior

The service has one Telegram worker:

- Interactive OpenClaw actions: priority `100`
- Fixed workflow runs: priority `10`

An interactive task can move ahead of fixed flows that have not started. The service never interrupts an already-running Telegram operation and never performs concurrent actions on the same session.

## OpenClaw plugin

The companion package is in [`openclaw-plugin/`](openclaw-plugin/).

```bash
cd openclaw-plugin
npm install
npm run build
openclaw plugins install "$PWD"
```

Example Gateway configuration:

```json5
{
  plugins: {
    entries: {
      "tg-sgk": {
        enabled: true,
        config: {
          baseUrl: "https://tg.example.com",
          apiKey: "same-value-as-TG_SGK_API_KEY",
          timeoutMs: 45000
        }
      }
    }
  },
  tools: {
    allow: ["tg-sgk"]
  }
}
```

Verify after restarting the Gateway:

```bash
openclaw plugins inspect tg-sgk --runtime --json
```

The plugin exposes:

- `tg_bot_inspect`
- `tg_send_message`
- `tg_get_recent_messages`
- `tg_wait_update`
- `tg_click_button`
- `tg_save_flow`
- `tg_list_flows`
- `tg_run_flow`
- `tg_get_history`

## First real acceptance test

Use one simple Telegram bot whose flow remains inside Telegram chat:

1. Run `tg_bot_inspect`.
2. Send `/start`.
3. Read the returned message and button list.
4. Click one harmless button.
5. Wait for a reply or edit.
6. Save the confirmed flow.
7. Run the saved flow.
8. Confirm the history contains a successful `run_flow` record.

Do not test first with payments, wallets, CAPTCHA, Mini Apps, or high-value accounts.

## Security notes

- Never commit `.env`, `.session`, SQLite databases, login codes, or two-factor passwords.
- Keep the repository private while it contains deployment-specific documentation.
- Use HTTPS for remote OpenClaw calls.
- Use a long random API key.
- Respect Telegram `FLOOD_WAIT` responses and each third-party bot's terms.
- This project intentionally refuses non-bot targets at the service boundary.
