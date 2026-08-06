#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

find_openclaw_container() {
  docker ps --format '{{.Names}} {{.Image}}' \
    | awk 'tolower($0) ~ /openclaw/ {print $1}'
}

OPENCLAW_CONTAINER="${OPENCLAW_CONTAINER:-}"
if [[ -z "$OPENCLAW_CONTAINER" ]]; then
  CANDIDATES="$(find_openclaw_container || true)"
  COUNT="$(printf '%s\n' "$CANDIDATES" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [[ "$COUNT" == "1" ]]; then
    OPENCLAW_CONTAINER="$CANDIDATES"
  else
    [[ "$COUNT" == "0" ]] || printf 'Detected OpenClaw containers:\n%s\n' "$CANDIDATES"
    read -r -p "OpenClaw container name: " OPENCLAW_CONTAINER
  fi
fi

[[ -n "$OPENCLAW_CONTAINER" ]] || die "OpenClaw container name is required"
docker inspect "$OPENCLAW_CONTAINER" >/dev/null 2>&1 || die "Container not found: $OPENCLAW_CONTAINER"
docker exec "$OPENCLAW_CONTAINER" sh -lc 'command -v openclaw >/dev/null' \
  || die "The selected container does not contain the openclaw CLI"

read_env_value() {
  local key="$1"
  [[ -f .env ]] || return 0
  sed -n "s/^${key}=//p" .env | tail -n 1
}

prompt_value() {
  local var_name="$1" prompt="$2" current="$3" secret="${4:-false}" value=""
  if [[ -n "$current" ]]; then
    printf '%s is already configured. Press Enter to keep it.\n' "$var_name"
  fi
  if [[ "$secret" == "true" ]]; then
    read -r -s -p "$prompt" value
    printf '\n'
  else
    read -r -p "$prompt" value
  fi
  [[ -n "$value" ]] || value="$current"
  [[ -n "$value" ]] || die "$var_name is required"
  printf -v "$var_name" '%s' "$value"
}

TG_API_ID="$(read_env_value TG_API_ID)"
TG_API_HASH="$(read_env_value TG_API_HASH)"
TG_PHONE="$(read_env_value TG_PHONE)"
TG_SGK_API_KEY="$(read_env_value TG_SGK_API_KEY)"

say "Telegram credentials"
prompt_value TG_API_ID "TG_API_ID: " "$TG_API_ID"
prompt_value TG_API_HASH "TG_API_HASH: " "$TG_API_HASH" true
prompt_value TG_PHONE "Telegram phone (example +8613800000000): " "$TG_PHONE"

if [[ -z "$TG_SGK_API_KEY" || "$TG_SGK_API_KEY" == "replace-with-a-long-random-key" ]]; then
  TG_SGK_API_KEY="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
fi

cat > .env <<ENV
TG_SGK_API_KEY=$TG_SGK_API_KEY
TG_API_ID=$TG_API_ID
TG_API_HASH=$TG_API_HASH
TG_PHONE=$TG_PHONE
TG_SESSION_PATH=/data/telegram-user
TG_MOCK=false
TG_SGK_DATA_DIR=/data
TG_SGK_DATABASE_PATH=/data/tg-sgk.sqlite3
TG_SGK_MIN_ACTION_INTERVAL_SECONDS=1.5
TG_SGK_DEFAULT_TIMEOUT_SECONDS=30
TG_SGK_DOMAIN=localhost
ENV
chmod 600 .env

say "Build tg-sgk"
docker compose build api login

say "Login to Telegram once"
printf 'Telegram will now ask for the login code and, if enabled, the 2FA password.\n'
docker compose --profile tools run --rm login

say "Start tg-sgk"
docker compose up -d api

for _ in $(seq 1 30); do
  if docker exec tg-sgk-api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" \
    >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

docker exec tg-sgk-api python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" \
  >/dev/null 2>&1 || die "tg-sgk API did not become healthy. Run: docker compose logs api"

say "Connect OpenClaw to tg-sgk private network"
if ! docker inspect -f '{{json .NetworkSettings.Networks}}' "$OPENCLAW_CONTAINER" | grep -q 'tg-sgk-net'; then
  docker network connect tg-sgk-net "$OPENCLAW_CONTAINER"
fi

say "Pack and install the OpenClaw plugin"
rm -f openclaw-plugin/*.tgz
PLUGIN_TGZ="$(docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "$ROOT_DIR/openclaw-plugin:/work" \
  -w /work \
  node:22-alpine sh -lc 'npm pack --silent' | tail -n 1)"
[[ -f "$ROOT_DIR/openclaw-plugin/$PLUGIN_TGZ" ]] || die "Plugin package was not created"

docker cp "$ROOT_DIR/openclaw-plugin/$PLUGIN_TGZ" \
  "$OPENCLAW_CONTAINER:/tmp/$PLUGIN_TGZ" >/dev/null

docker exec "$OPENCLAW_CONTAINER" \
  openclaw plugins install "npm-pack:/tmp/$PLUGIN_TGZ" --force

say "Configure OpenClaw plugin"
docker exec -i "$OPENCLAW_CONTAINER" openclaw config patch --stdin <<JSON
{
  plugins: {
    entries: {
      "tg-sgk": {
        enabled: true,
        config: {
          baseUrl: "http://tg-sgk-api:8000",
          apiKey: "$TG_SGK_API_KEY",
          timeoutMs: 45000
        }
      }
    }
  }
}
JSON

TOOLS_ALLOW="$(docker exec "$OPENCLAW_CONTAINER" openclaw config get tools.allow --json 2>/dev/null || true)"
if [[ "$TOOLS_ALLOW" == \[* ]]; then
  UPDATED_TOOLS_ALLOW="$(docker exec "$OPENCLAW_CONTAINER" node -e '
    const tools = JSON.parse(process.argv[1]);
    if (!tools.includes("tg-sgk")) tools.push("tg-sgk");
    process.stdout.write(JSON.stringify(tools));
  ' "$TOOLS_ALLOW")"
  docker exec "$OPENCLAW_CONTAINER" \
    openclaw config set tools.allow "$UPDATED_TOOLS_ALLOW" --strict-json
fi

docker exec "$OPENCLAW_CONTAINER" openclaw config validate >/dev/null

docker restart "$OPENCLAW_CONTAINER" >/dev/null
sleep 4

say "Verify network, Telegram login, and plugin"
docker exec -i "$OPENCLAW_CONTAINER" node - "$TG_SGK_API_KEY" <<'NODE'
const apiKey = process.argv[2];
const response = await fetch('http://tg-sgk-api:8000/v1/bots/inspect', {
  method: 'POST',
  headers: {
    'content-type': 'application/json',
    authorization: `Bearer ${apiKey}`,
  },
  body: JSON.stringify({ bot: '@BotFather' }),
});
const body = await response.text();
if (!response.ok) {
  console.error(body);
  process.exit(1);
}
console.log(body);
NODE

docker exec "$OPENCLAW_CONTAINER" \
  openclaw plugins inspect tg-sgk --runtime --json >/dev/null

cat <<DONE

============================================================
Setup complete.

Open your normal OpenClaw chat and send exactly this:

  使用 tg_bot_inspect 检查 @BotFather 是否为机器人，只检查，不要发送消息。

Then test a real bot with:

  向 @your_bot 发送 /start，读取回复和按钮，但先不要点击。

OpenClaw container: $OPENCLAW_CONTAINER
tg-sgk container:  tg-sgk-api
Private network:    tg-sgk-net
============================================================
DONE
