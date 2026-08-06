#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$ROOT_DIR/openclaw-plugin"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v openclaw >/dev/null 2>&1 || die "openclaw CLI is required in this environment"
command -v node >/dev/null 2>&1 || die "Node.js is required"
command -v npm >/dev/null 2>&1 || die "npm is required"
[[ -f "$PLUGIN_DIR/package.json" ]] || die "openclaw-plugin/package.json was not found"

prompt() {
  local name="$1" label="$2" secret="${3:-false}" current="${!name:-}" value=""
  if [[ -n "$current" ]]; then
    printf '%s is already set; press Enter to keep it.\n' "$name"
  fi
  if [[ "$secret" == "true" ]]; then
    read -r -s -p "$label" value
    printf '\n'
  else
    read -r -p "$label" value
  fi
  [[ -n "$value" ]] || value="$current"
  [[ -n "$value" ]] || die "$name is required"
  printf -v "$name" '%s' "$value"
}

TG_API_ID="${TG_API_ID:-}"
TG_API_HASH="${TG_API_HASH:-}"
TG_PHONE="${TG_PHONE:-}"

say "Telegram application credentials"
prompt TG_API_ID "TG_API_ID: "
prompt TG_API_HASH "TG_API_HASH: " true
prompt TG_PHONE "Telegram phone with country code (example +8613800000000): "
[[ "$TG_API_ID" =~ ^[0-9]+$ ]] || die "TG_API_ID must be an integer"

say "Pack direct OpenClaw plugin"
TGZ_NAME="$(cd "$PLUGIN_DIR" && npm pack --silent --pack-destination "$TMP_DIR" | tail -n 1)"
TGZ_PATH="$TMP_DIR/$TGZ_NAME"
[[ -f "$TGZ_PATH" ]] || die "Plugin package was not created"

say "Replace old tg-sgk installation"
openclaw plugins uninstall tg-sgk --force >/dev/null 2>&1 || true
openclaw plugins install "npm-pack:$TGZ_PATH" --force

say "Configure plugin"
PATCH_FILE="$TMP_DIR/tg-sgk.patch.json"
TG_API_ID="$TG_API_ID" TG_API_HASH="$TG_API_HASH" TG_PHONE="$TG_PHONE" node > "$PATCH_FILE" <<'NODE'
const patch = {
  plugins: {
    entries: {
      "tg-sgk": {
        enabled: true,
        config: {
          apiId: Number(process.env.TG_API_ID),
          apiHash: process.env.TG_API_HASH,
          phone: process.env.TG_PHONE,
          actionIntervalMs: 1200,
          defaultTimeoutMs: 30000
        }
      }
    }
  }
};
process.stdout.write(JSON.stringify(patch, null, 2));
NODE
openclaw config patch --file "$PATCH_FILE"

TOOLS_ALLOW="$(openclaw config get tools.allow --json 2>/dev/null || true)"
if [[ "$TOOLS_ALLOW" == \[* ]]; then
  UPDATED_TOOLS_ALLOW="$(node -e '
    const tools = JSON.parse(process.argv[1]);
    if (!tools.includes("tg-sgk")) tools.push("tg-sgk");
    process.stdout.write(JSON.stringify(tools));
  ' "$TOOLS_ALLOW")"
  openclaw config set tools.allow "$UPDATED_TOOLS_ALLOW" --strict-json
fi

openclaw plugins enable tg-sgk >/dev/null
openclaw config validate >/dev/null

say "Verify plugin runtime"
openclaw plugins inspect tg-sgk --runtime --json >/dev/null

cat <<'DONE'

============================================================
TG SGK direct plugin is installed.

No Docker, Python service, domain, HTTPS, or sidecar network is used.

Open your normal OpenClaw chat and send:

  检查 Telegram 登录状态；如果未登录，就使用 tg_auth_send_code 给我发送验证码。

After Telegram sends the code, reply:

  Telegram 验证码是 12345，请使用 tg_auth_submit_code 登录。

After login, test:

  使用 tg_bot_inspect 检查 @BotFather 是否为机器人，只检查，不发送消息。
============================================================
DONE

# A managed Gateway may reload automatically. Restart explicitly when supported.
openclaw gateway restart >/dev/null 2>&1 || true
