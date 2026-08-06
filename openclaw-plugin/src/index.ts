import { Type, type Static } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

const configSchema = Type.Object(
  {
    baseUrl: Type.String({ minLength: 8, description: "tg-sgk service base URL" }),
    apiKey: Type.String({ minLength: 8, description: "tg-sgk Bearer API key" }),
    timeoutMs: Type.Optional(Type.Number({ minimum: 1000, maximum: 180000 })),
  },
  { additionalProperties: false },
);

type PluginConfig = Static<typeof configSchema>;

type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

async function request(
  config: PluginConfig,
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<JsonValue> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.timeoutMs ?? 45_000);
  const relayAbort = () => controller.abort();
  signal?.addEventListener("abort", relayAbort, { once: true });

  try {
    const response = await fetch(`${config.baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${config.apiKey}`,
        ...(init.headers ?? {}),
      },
    });
    const payload = (await response.json()) as JsonValue;
    if (!response.ok) {
      throw new Error(`tg-sgk ${response.status}: ${JSON.stringify(payload)}`);
    }
    return payload;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", relayAbort);
  }
}

const flowStepSchema = Type.Object(
  {
    action: Type.Union([
      Type.Literal("send_message"),
      Type.Literal("wait_message"),
      Type.Literal("click_button"),
      Type.Literal("wait_message_or_edit"),
      Type.Literal("sleep"),
      Type.Literal("assert_text"),
    ]),
    text: Type.Optional(Type.String()),
    row: Type.Optional(Type.Integer({ minimum: 0 })),
    column: Type.Optional(Type.Integer({ minimum: 0 })),
    timeout_seconds: Type.Optional(Type.Number({ minimum: 0.1, maximum: 120 })),
    seconds: Type.Optional(Type.Number({ minimum: 0, maximum: 60 })),
    contains_any: Type.Optional(Type.Array(Type.String(), { minItems: 1 })),
  },
  { additionalProperties: false },
);

export default defineToolPlugin({
  id: "tg-sgk",
  name: "TG SGK",
  description: "Bot-only Telegram user automation through a separate tg-sgk service.",
  configSchema,
  tools: (tool: (definition: unknown) => unknown) => [
    tool({
      name: "tg_bot_inspect",
      label: "Inspect Telegram Bot",
      description:
        "Verify that a Telegram target is a bot before any interaction. Human users, groups, and channels are rejected by the service.",
      parameters: Type.Object({ bot: Type.String({ minLength: 2 }) }),
      execute: ({ bot }: { bot: string }, config: PluginConfig, context: { signal?: AbortSignal }) =>
        request(config, "/v1/bots/inspect", { method: "POST", body: JSON.stringify({ bot }) }, context.signal),
    }),
    tool({
      name: "tg_send_message",
      label: "Send Message to Telegram Bot",
      description:
        "Send text or a command to a verified Telegram bot. This tool cannot message human accounts, groups, or channels.",
      parameters: Type.Object({
        bot: Type.String({ minLength: 2 }),
        text: Type.String({ minLength: 1, maxLength: 4096 }),
      }),
      execute: (
        params: { bot: string; text: string },
        config: PluginConfig,
        context: { signal?: AbortSignal },
      ) =>
        request(
          config,
          "/v1/messages/send",
          { method: "POST", body: JSON.stringify(params) },
          context.signal,
        ),
    }),
    tool({
      name: "tg_get_recent_messages",
      label: "Read Telegram Bot Messages",
      description: "Read recent messages and available buttons from a verified Telegram bot.",
      parameters: Type.Object({
        bot: Type.String({ minLength: 2 }),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
      }),
      execute: (
        { bot, limit = 10 }: { bot: string; limit?: number },
        config: PluginConfig,
        context: { signal?: AbortSignal },
      ) =>
        request(
          config,
          `/v1/messages/recent?bot=${encodeURIComponent(bot)}&limit=${limit}`,
          {},
          context.signal,
        ),
    }),
    tool({
      name: "tg_wait_update",
      label: "Wait for Telegram Bot Update",
      description: "Wait for a new bot message or an edit to a known bot message.",
      parameters: Type.Object({
        bot: Type.String({ minLength: 2 }),
        after_message_id: Type.Optional(Type.Integer()),
        watch_message_id: Type.Optional(Type.Integer()),
        previous_signature: Type.Optional(Type.String()),
        timeout_seconds: Type.Optional(Type.Number({ minimum: 1, maximum: 120 })),
      }),
      execute: (
        params: Record<string, unknown>,
        config: PluginConfig,
        context: { signal?: AbortSignal },
      ) =>
        request(
          config,
          "/v1/messages/wait",
          { method: "POST", body: JSON.stringify(params) },
          context.signal,
        ),
    }),
    tool({
      name: "tg_click_button",
      label: "Click Telegram Bot Button",
      description:
        "Click one button in a verified Telegram bot message, selected either by exact text or row and column.",
      parameters: Type.Object({
        bot: Type.String({ minLength: 2 }),
        message_id: Type.Integer(),
        text: Type.Optional(Type.String({ minLength: 1 })),
        row: Type.Optional(Type.Integer({ minimum: 0 })),
        column: Type.Optional(Type.Integer({ minimum: 0 })),
      }),
      execute: (
        params: Record<string, unknown>,
        config: PluginConfig,
        context: { signal?: AbortSignal },
      ) =>
        request(
          config,
          "/v1/buttons/click",
          { method: "POST", body: JSON.stringify(params) },
          context.signal,
        ),
    }),
    tool({
      name: "tg_save_flow",
      label: "Save Telegram Bot Flow",
      description:
        "Save or update a confirmed fixed Telegram bot workflow. Use after the operator has approved the explored steps.",
      parameters: Type.Object({
        id: Type.String({ minLength: 2, maxLength: 64 }),
        name: Type.String({ minLength: 1, maxLength: 128 }),
        bot: Type.String({ minLength: 2 }),
        steps: Type.Array(flowStepSchema, { minItems: 1, maxItems: 50 }),
      }),
      execute: (
        params: Record<string, unknown>,
        config: PluginConfig,
        context: { signal?: AbortSignal },
      ) =>
        request(
          config,
          "/v1/flows",
          { method: "POST", body: JSON.stringify(params) },
          context.signal,
        ),
    }),
    tool({
      name: "tg_list_flows",
      label: "List Telegram Bot Flows",
      description: "List fixed Telegram bot workflows stored by the tg-sgk service.",
      parameters: Type.Object({}),
      execute: (_params: object, config: PluginConfig, context: { signal?: AbortSignal }) =>
        request(config, "/v1/flows", {}, context.signal),
    }),
    tool({
      name: "tg_run_flow",
      label: "Run Telegram Bot Flow",
      description:
        "Run one previously confirmed fixed Telegram bot workflow. Fixed flows execute without model reasoning.",
      parameters: Type.Object({ flow_id: Type.String({ minLength: 2, maxLength: 64 }) }),
      execute: (
        { flow_id }: { flow_id: string },
        config: PluginConfig,
        context: { signal?: AbortSignal },
      ) => request(config, `/v1/flows/${encodeURIComponent(flow_id)}/run`, { method: "POST" }, context.signal),
    }),
    tool({
      name: "tg_get_history",
      label: "Get Telegram Automation History",
      description: "Read basic execution history for diagnosis and flow repair.",
      parameters: Type.Object({
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
        target: Type.Optional(Type.String()),
      }),
      execute: (
        { limit = 50, target }: { limit?: number; target?: string },
        config: PluginConfig,
        context: { signal?: AbortSignal },
      ) => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (target) query.set("target", target);
        return request(config, `/v1/history?${query.toString()}`, {}, context.signal);
      },
    }),
  ],
});
