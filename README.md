# tg-sgk

让 OpenClaw 使用一个 Telegram **个人账号**操作第三方机器人。插件会在每次操作前验证目标 `bot === true`，拒绝真人、群组和频道。

## 当前架构：直接插件模式

```text
OpenClaw Gateway
  └─ tg-sgk 插件（Node.js + teleproto）
       ├─ Telegram MTProto 连接
       └─ $OPENCLAW_STATE_DIR/tg-sgk/session.txt
```

不再需要：

- Docker 或 Docker Compose
- Python / FastAPI / Telethon sidecar
- `tg-sgk-api` 容器
- 私有 Docker 网络
- 域名、Caddy 或 HTTPS API

`teleproto` 是纯 JavaScript MTProto 客户端，依赖会由 OpenClaw 的插件安装器安装。

## 最小化安装

在能够运行 `openclaw` CLI 的同一个环境中：

```bash
git clone https://github.com/Duangdang233/tg-sgk.git
cd tg-sgk
bash quickstart.sh
```

已经克隆时：

```bash
cd tg-sgk
git pull --ff-only
bash quickstart.sh
```

脚本只要求：

1. Telegram `api_id`
2. Telegram `api_hash`
3. 带国家码的手机号

脚本会安装插件、写入配置、检查运行时注册并尝试重启 Gateway。

## 第一次登录

回到日常使用的 OpenClaw 对话，发送：

```text
检查 Telegram 登录状态；如果未登录，就使用 tg_auth_send_code 给我发送验证码。
```

收到 Telegram 验证码后发送：

```text
Telegram 验证码是 12345，请使用 tg_auth_submit_code 登录。
```

开启 Telegram 两步验证时，OpenClaw 会提示调用 `tg_auth_submit_password`。为了降低风险，建议使用专门的 Telegram 自动化账号。

登录成功后 Session 保存在：

```text
$OPENCLAW_STATE_DIR/tg-sgk/session.txt
```

默认是：

```text
~/.openclaw/tg-sgk/session.txt
```

OpenClaw 的状态目录应使用持久化存储；只要该目录保留，替换运行环境后无需重新登录。

## 最小验收

```text
使用 tg_bot_inspect 检查 @BotFather 是否为机器人，只检查，不发送消息。
```

然后测试一个无风险机器人：

```text
向 @example_bot 发送 /start，读取最新回复和按钮，但先不要点击。
```

确认按钮后：

```text
点击 @example_bot 消息 ID 12345 中名为“每日签到”的按钮，然后读取结果。
```

## 工具

登录：

- `tg_auth_status`
- `tg_auth_send_code`
- `tg_auth_submit_code`
- `tg_auth_submit_password`

Telegram 操作：

- `tg_bot_inspect`
- `tg_send_message`
- `tg_get_recent_messages`
- `tg_wait_update`
- `tg_click_button`

固定流程和记录：

- `tg_save_flow`
- `tg_list_flows`
- `tg_run_flow`
- `tg_get_history`

## 安全边界

- 只允许操作 Telegram Bot。
- 不支持群组、频道或真人私聊。
- 不支持 Mini App、网页、支付、钱包或验证码绕过。
- Session、流程和历史记录只保存在 OpenClaw 本地状态目录，不进入 Git 仓库。

## 旧文件说明

仓库中仍可能保留早期 sidecar 原型文件，但当前安装入口只使用 `openclaw-plugin/` 和 `quickstart.sh`。旧 Docker/Python 文件不参与运行。
