# tg-sgk

让 OpenClaw 使用你的 Telegram **个人账号**操作第三方机器人。服务端强制校验目标必须是 Bot，拒绝真人、群组和频道。

## 最小化跑通

### 前提

- `tg-sgk` 与现有 OpenClaw Docker 容器运行在同一台机器。
- 已安装 Docker 和 Docker Compose v2。
- 在 `my.telegram.org` 创建应用并取得 `api_id`、`api_hash`。

### 一条命令安装

```bash
git clone https://github.com/Duangdang233/tg-sgk.git
cd tg-sgk
bash quickstart.sh
```

仓库是私有仓库时，GitHub 会要求使用已登录的凭据或 Personal Access Token。不要使用 `git@github.com:...`，除非当前机器已经配置 SSH 客户端和私钥。

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
- 打包并安装零编译 JavaScript 插件
- 写入插件配置并重启 OpenClaw
- 用 `@BotFather` 验证 Telegram 登录、网络和插件注册

插件不需要执行 `npm install`、`npm run build` 或 TypeScript 编译。

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
