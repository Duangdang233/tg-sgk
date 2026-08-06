# TG SGK OpenClaw plugin

This plugin runs directly inside OpenClaw and connects to Telegram through MTProto. It does not require Docker, Python, a sidecar API, a domain, or HTTPS.

Install it through the repository `quickstart.sh`, then use `tg_setup_credentials` in an OpenClaw chat to store `apiId`, `apiHash`, and `phone`. Continue with `tg_auth_send_code` and `tg_auth_submit_code`.

Persistent credentials, the Telegram session, flows, and history are stored under `$OPENCLAW_STATE_DIR/tg-sgk` (default `~/.openclaw/tg-sgk`).

The plugin uses pure-JavaScript `teleproto` and rejects targets that are not Telegram bots.
