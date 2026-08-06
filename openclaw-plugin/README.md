# OpenClaw TG SGK plugin

This package exposes the `tg-sgk` HTTPS API as OpenClaw tools. The Telegram login session remains in the separate service and is never stored in the plugin.

## Build

```bash
npm install
npm run build
```

## Install locally

```bash
openclaw plugins install /path/to/tg-sgk/openclaw-plugin
```

Configure the plugin in the OpenClaw Gateway configuration:

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

Restart the Gateway and verify:

```bash
openclaw plugins inspect tg-sgk --runtime --json
```
