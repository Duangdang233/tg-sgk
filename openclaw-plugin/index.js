import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const object = (properties = {}, required = []) => ({
  type: "object",
  additionalProperties: false,
  properties,
  ...(required.length ? { required } : {}),
});
const string = (extra = {}) => ({ type: "string", ...extra });
const integer = (extra = {}) => ({ type: "integer", ...extra });
const number = (extra = {}) => ({ type: "number", ...extra });

const configSchema = object({
  baseUrl: string({ minLength: 8 }),
  apiKey: string({ minLength: 8 }),
  timeoutMs: number({ minimum: 1000, maximum: 180000, default: 45000 }),
}, ["baseUrl", "apiKey"]);

const flowStepSchema = object({
  action: string({ enum: [
    "send_message", "wait_message", "click_button",
    "wait_message_or_edit", "sleep", "assert_text",
  ] }),
  text: string(),
  row: integer({ minimum: 0 }),
  column: integer({ minimum: 0 }),
  timeout_seconds: number({ minimum: 0.1, maximum: 120 }),
  seconds: number({ minimum: 0, maximum: 60 }),
  contains_any: { type: "array", minItems: 1, items: string() },
}, ["action"]);

function getConfig(api) {
  const raw = api.pluginConfig ?? {};
  const config = {
    baseUrl: typeof raw.baseUrl === "string" ? raw.baseUrl.replace(/\/$/, "") : "",
    apiKey: typeof raw.apiKey === "string" ? raw.apiKey : "",
    timeoutMs: typeof raw.timeoutMs === "number" ? raw.timeoutMs : 45_000,
  };
  if (!config.baseUrl || !config.apiKey) {
    throw new Error("tg-sgk requires plugin config: baseUrl and apiKey");
  }
  return config;
}

async function call(config, path, init = {}, signal) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  try {
    const response = await fetch(`${config.baseUrl}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${config.apiKey}`,
        ...(init.headers ?? {}),
      },
    });
    const text = await response.text();
    let payload;
    try { payload = text ? JSON.parse(text) : null; }
    catch { payload = { raw: text }; }
    if (!response.ok) throw new Error(`tg-sgk ${response.status}: ${JSON.stringify(payload)}`);
    return payload;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

const output = (payload) => ({
  content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
  details: payload && typeof payload === "object" && !Array.isArray(payload)
    ? payload : { result: payload },
});

function add(api, config, name, description, parameters, handler) {
  api.registerTool({
    name, description, parameters,
    async execute(_id, params, context) {
      return output(await handler(params, context?.signal));
    },
  });
}

export default definePluginEntry({
  id: "tg-sgk",
  name: "TG SGK",
  description: "Bot-only Telegram automation through the tg-sgk service.",
  configSchema,
  register(api) {
    const config = getConfig(api);
    const post = (path, params, signal) => call(config, path, {
      method: "POST", body: JSON.stringify(params),
    }, signal);

    add(api, config, "tg_bot_inspect", "Verify a Telegram target is a bot without messaging it.",
      object({ bot: string({ minLength: 2 }) }, ["bot"]),
      (p, s) => post("/v1/bots/inspect", p, s));

    add(api, config, "tg_send_message", "Send text or a command to a verified Telegram bot.",
      object({ bot: string({ minLength: 2 }), text: string({ minLength: 1, maxLength: 4096 }) }, ["bot", "text"]),
      (p, s) => post("/v1/messages/send", p, s));

    add(api, config, "tg_get_recent_messages", "Read recent bot messages and buttons.",
      object({ bot: string({ minLength: 2 }), limit: integer({ minimum: 1, maximum: 50, default: 10 }) }, ["bot"]),
      ({ bot, limit = 10 }, s) => call(config, `/v1/messages/recent?bot=${encodeURIComponent(bot)}&limit=${limit}`, {}, s));

    add(api, config, "tg_wait_update", "Wait for a new or edited bot message.",
      object({
        bot: string({ minLength: 2 }), after_message_id: integer(), watch_message_id: integer(),
        previous_signature: string(), timeout_seconds: number({ minimum: 1, maximum: 120, default: 30 }),
      }, ["bot"]), (p, s) => post("/v1/messages/wait", p, s));

    add(api, config, "tg_click_button", "Click a bot button by exact text or row and column.",
      object({
        bot: string({ minLength: 2 }), message_id: integer(), text: string({ minLength: 1 }),
        row: integer({ minimum: 0 }), column: integer({ minimum: 0 }),
      }, ["bot", "message_id"]), (p, s) => post("/v1/buttons/click", p, s));

    add(api, config, "tg_save_flow", "Save or update an operator-confirmed fixed bot workflow.",
      object({
        id: string({ minLength: 2, maxLength: 64 }), name: string({ minLength: 1, maxLength: 128 }),
        bot: string({ minLength: 2 }), steps: { type: "array", minItems: 1, maxItems: 50, items: flowStepSchema },
      }, ["id", "name", "bot", "steps"]), (p, s) => post("/v1/flows", p, s));

    add(api, config, "tg_list_flows", "List saved Telegram bot workflows.", object(),
      (_p, s) => call(config, "/v1/flows", {}, s));

    add(api, config, "tg_run_flow", "Run a previously confirmed fixed bot workflow.",
      object({ flow_id: string({ minLength: 2, maxLength: 64 }) }, ["flow_id"]),
      ({ flow_id }, s) => call(config, `/v1/flows/${encodeURIComponent(flow_id)}/run`, { method: "POST" }, s));

    add(api, config, "tg_get_history", "Read tg-sgk execution history.",
      object({ limit: integer({ minimum: 1, maximum: 200, default: 50 }), target: string() }),
      ({ limit = 50, target }, s) => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (target) query.set("target", target);
        return call(config, `/v1/history?${query}`, {}, s);
      });
  },
});
