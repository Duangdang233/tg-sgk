# TG SGK OpenClaw plugin

This plugin runs directly inside OpenClaw and connects to Telegram through MTProto. It does not require Docker, Python, a sidecar API, a domain, or HTTPS.

Persistent state is stored under `$OPENCLAW_STATE_DIR/tg-sgk` (default `~/.openclaw/tg-sgk`).

The plugin depends on pure-JavaScript `teleproto` and exposes Telegram authorization, bot-only messaging, button interaction, saved flows, and local history as OpenClaw tools.
