# OpenClaw TG SGK plugin

This package exposes the `tg-sgk` API as nine OpenClaw tools. It ships as plain ESM JavaScript and requires no TypeScript compilation or local dependency installation.

The Telegram login session remains in the separate `tg-sgk` service and is never stored in this plugin.

## Verify package

```bash
node --check index.js
npm pack --dry-run
```

## Install

The repository root `quickstart.sh` packs, installs, configures, and verifies this plugin automatically.

Manual installation from a packed artifact is also supported:

```bash
npm pack
openclaw plugins install npm-pack:./duangdang233-openclaw-tg-sgk-0.1.1.tgz --force
```

Configure `plugins.entries.tg-sgk.config` with:

```json5
{
  baseUrl: "http://tg-sgk-api:8000",
  apiKey: "same-value-as-TG_SGK_API_KEY",
  timeoutMs: 45000
}
```

Restart the Gateway and verify:

```bash
openclaw plugins inspect tg-sgk --runtime --json
```
