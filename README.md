# tg-sgk

让 OpenClaw 使用一个 Telegram **个人账号**操作第三方机器人。插件会在每次操作前验证目标 `bot === true`，拒绝真人、群组和频道。

## 当前架构：OpenClaw 直连 Telegram

```text
OpenClaw Gateway
  └─ tg-sgk 插件（Node.js + teleproto）
       ├─ Telegram MTProto 连接
       └─ $OPENCLAW_STATE_DIR/tg-sgk/
```

不需要 Docker、Python 服务、`tg-sgk-api`、容器网络、域名、Caddy 或 HTTPS API。

## 最小化安装

在能够运行 `openclaw` CLI 的环境中：

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

脚本不再要求终端输入任何 Telegram 凭据，只负责安装并启用插件。

## 在 OpenClaw 对话中完成配置和登录

先发送：

```text
使用 tg_setup_credentials 配置 Telegram：
apiId：你的 API ID
apiHash：你的 API Hash
phone：带国家码的手机号
```

再发送：

```text
检查 Telegram 登录状态；如果未登录，就使用 tg_auth_send_code 给我发送验证码。
```

收到 Telegram 验证码后发送：

```text
Telegram 验证码是 12345，请使用 tg_auth_submit_code 登录。
```

开启两步验证时，再按提示调用 `tg_auth_submit_password`。建议使用专门的 Telegram 自动化账号。

凭据、Session、流程和历史记录默认保存在：

```text
$OPENCLAW_STATE_DIR/tg-sgk/
```

默认路径为 `~/.openclaw/tg-sgk/`。请确保 OpenClaw 状态目录使用持久化存储。

## 最小验收

```text
使用 tg_bot_inspect 检查 @BotFather 是否为机器人，只检查，不发送消息。
```

然后测试一个无风险机器人：

```text
向 @example_bot 发送 /start，读取最新回复和按钮，但先不要点击。
```

## 工具

配置与登录：

- `tg_setup_credentials`
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

固定流程与记录：

- `tg_save_flow`
- `tg_list_flows`
- `tg_run_flow`
- `tg_get_history`

## 安全边界

- 只允许操作 Telegram Bot。
- 不支持群组、频道或真人私聊。
- 不支持 Mini App、网页、支付、钱包或验证码绕过。
- 本地状态文件不会进入 Git 仓库。

仓库中仍可能保留早期 sidecar 原型文件，但当前运行只使用 `openclaw-plugin/` 和 `quickstart.sh`。
