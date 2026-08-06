#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$ROOT_DIR/openclaw-plugin"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v openclaw >/dev/null 2>&1 || die "openclaw CLI is required in this environment"
command -v npm >/dev/null 2>&1 || die "npm is required"
[[ -f "$PLUGIN_DIR/package.json" ]] || die "openclaw-plugin/package.json was not found"

say "Pack direct OpenClaw plugin"
TGZ_NAME="$(cd "$PLUGIN_DIR" && npm pack --silent --pack-destination "$TMP_DIR" | tail -n 1)"
TGZ_PATH="$TMP_DIR/$TGZ_NAME"
[[ -f "$TGZ_PATH" ]] || die "Plugin package was not created"

say "Replace old tg-sgk installation"
openclaw plugins uninstall tg-sgk --force >/dev/null 2>&1 || true
openclaw plugins install "npm-pack:$TGZ_PATH" --force

say "Enable plugin"
PATCH_FILE="$TMP_DIR/tg-sgk.patch.json"
cat > "$PATCH_FILE" <<'JSON'
{
  "plugins": {
    "entries": {
      "tg-sgk": {
        "enabled": true,
        "config": {}
      }
    }
  }
}
JSON
openclaw config patch --file "$PATCH_FILE"
openclaw plugins enable tg-sgk >/dev/null
openclaw config validate >/dev/null
openclaw plugins inspect tg-sgk --json >/dev/null

cat <<'DONE'

============================================================
TG SGK direct plugin is installed.

No Docker, Python service, terminal credential prompts, domain, HTTPS,
or sidecar network is used.

Open your normal OpenClaw chat and send:

  使用 tg_setup_credentials 配置 Telegram：
  apiId：你的 API ID
  apiHash：你的 API Hash
  phone：带国家码的手机号

Then send:

  检查 Telegram 登录状态；如果未登录，就使用 tg_auth_send_code 给我发送验证码。

After Telegram sends the code, reply:

  Telegram 验证码是 12345，请使用 tg_auth_submit_code 登录。
============================================================
DONE

# Managed Gateways may reload automatically. Restart explicitly when supported.
openclaw gateway restart >/dev/null 2>&1 || true
