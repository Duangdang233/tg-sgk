# tg-sgk

> Bot-only Telegram user automation service for OpenClaw.

让 OpenClaw 使用你的 Telegram **个人账号**操作第三方机器人。服务端强制校验目标必须是 Bot，拒绝真人、群组和频道。

## 项目简介

- FastAPI 服务，统一暴露 Telegram Bot 自动化 API。
- 通过 Telethon 复用你的 Telegram 个人账号 Session。
- 服务端强制限制目标必须是 Bot，不允许真人、群组和频道。
- 自带 OpenClaw 插件，可直接在 OpenClaw 中调用。

## Open source status

This repository is published under the MIT License. Before running it in production, read the security boundary below and keep your Telegram credentials, session files, `.env`, and local database private.

## 最小化跑通

### 前提

- `tg-sgk` 与现有 OpenClaw Docker 容器运行在同一台机器。
- 已安装 Docker 和 Docker Compose v2。
- 在 `my.telegram.org` 创建应用并取得 `api_id`、`api_hash`。

### 一条命令安装

```bash
git clone git@github.com:Duangdang233/tg-sgk.git
cd tg-sgk
bash quickstart.sh
```

脚本只会要求你输入：

1. `TG_API_ID`
2. `TG_API_HASH`
3. Telegram 手机号
4. OpenClaw 容器名（只有无法自动识别时才询问）

随后脚本会自动：

- 生成 API Key 和 `.env`
- 创建 Telegram 登录 Session
- 启动 `tg-sgk-api`
- 把它与 OpenClaw 接入同一个私有 Docker 网络
- 将预编译插件打包并安装到 OpenClaw
- 写入插件配置并重启 OpenClaw
- 用 `@BotFather` 验证 Telegram 登录、网络和插件注册

完成后，在你平常使用的 OpenClaw 对话里发送：

```text
使用 tg_bot_inspect 检查 @BotFather 是否为机器人，只检查，不要发送消息。
```

然后测试一个真实机器人：

```text
向 @your_bot 发送 /start，读取回复和按钮，但先不要点击。
```

## 日常使用

探索机器人：

```text
检查 @example_bot，发送 /start，读取最新回复和按钮，不要自动点击。
```

点击按钮：

```text
点击 @example_bot 消息 ID 12345 中名为“每日签到”的按钮，然后读取结果。
```

保存固定流程：

```text
把刚才的操作保存为流程 example-checkin，以后直接运行，不需要重新分析。
```

运行固定流程：

```text
运行 example-checkin。
```

## quickstart 的部署结构

```text
OpenClaw 容器
    │ tg-sgk OpenClaw 插件
    │ Docker 私有网络 tg-sgk-net
    ▼
tg-sgk-api 容器
    │ Telethon Session
    ▼
Telegram 第三方机器人
```

测试模式不需要域名、HTTPS、Caddy，也不需要修改 OpenClaw 的 `docker-compose.yml`。

## 更新

```bash
cd tg-sgk
git pull
bash quickstart.sh
```

脚本可重复执行，会复用 Telegram Session 和现有配置。

## 常用排错

```bash
# tg-sgk 状态
docker ps --filter name=tg-sgk-api
docker logs --tail=100 tg-sgk-api

# 查看 OpenClaw 容器
docker ps --format '{{.Names}} {{.Image}}' | grep -i openclaw

# 检查插件
OPENCLAW_CONTAINER=<你的容器名>
docker exec "$OPENCLAW_CONTAINER" openclaw plugins inspect tg-sgk --runtime --json

# 验证 API 网络
docker exec "$OPENCLAW_CONTAINER" node -e \
  "fetch('http://tg-sgk-api:8000/health').then(r=>r.text()).then(console.log)"
```

OpenClaw 容器被重新创建后，重新执行一次 `bash quickstart.sh`，脚本会重新连接私有网络并恢复插件配置。

## 安全边界

- 所有 API 操作都会验证 `entity.bot == true`。
- 不允许向真人、群组和频道发送消息。
- 不支持 Mini App、网页、支付、钱包和验证码绕过。
- Telegram Session 只保存在 Docker 卷 `tg_data` 中，不进入 OpenClaw，也不会上传 GitHub。
- `.env`、Session、数据库、验证码和两步验证密码禁止提交。

## 开源协作

- 贡献说明：见 `CONTRIBUTING.md`
- 安全披露：见 `SECURITY.md`
- 社区行为准则：见 `CODE_OF_CONDUCT.md`

## 开发测试

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
ruff check app tests
```

## 可选：以后启用公网 HTTPS

最小流程跑通后，再配置 `TG_SGK_DOMAIN` 并启动：

```bash
docker compose --profile https up -d caddy
```

这不是首次测试的必要步骤。

## License

MIT. See `LICENSE`.
