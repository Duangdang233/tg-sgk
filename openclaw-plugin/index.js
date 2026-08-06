import { mkdir, readFile, writeFile, appendFile, rename } from "node:fs/promises";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Type } from "typebox";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { TelegramClient } from "teleproto";
import { StringSession } from "teleproto/sessions";

const PLUGIN_ID = "tg-sgk";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function jsonSafe(value, seen = new WeakSet()) {
  if (value === null || value === undefined) return value ?? null;
  if (typeof value === "bigint") return value.toString();
  if (typeof value !== "object") return value;
  const name = value?.constructor?.name || "";
  if ((name === "BigInteger" || name === "BN") && typeof value.toString === "function") return value.toString();
  if (value instanceof Date) return value.toISOString();
  if (Buffer.isBuffer(value)) return value.toString("base64");
  if (seen.has(value)) return "[Circular]";
  seen.add(value);
  if (Array.isArray(value)) return value.map((item) => jsonSafe(item, seen));
  const output = {};
  for (const [key, item] of Object.entries(value)) output[key] = jsonSafe(item, seen);
  return output;
}

const textResult = (data) => ({
  content: [{ type: "text", text: JSON.stringify(jsonSafe(data), null, 2) }],
  details: jsonSafe(data),
});

function safeError(error) {
  return {
    name: error?.name || "Error",
    code: error?.errorMessage || error?.code || undefined,
    message: error?.message || String(error),
  };
}

function stateRoot(config) {
  const base = process.env.OPENCLAW_STATE_DIR || join(homedir(), ".openclaw");
  return config.stateDir || join(base, "tg-sgk");
}

async function atomicWrite(path, content, mode = 0o600) {
  const temporary = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, content, { encoding: "utf8", mode });
  await rename(temporary, path);
}

function normalizeBot(bot) {
  const value = String(bot || "").trim();
  if (!value) throw new Error("bot is required");
  return value.startsWith("@") ? value : `@${value}`;
}

class TgSgkRuntime {
  constructor(api) {
    this.api = api;
    this.config = {
      apiId: Number(api.pluginConfig?.apiId),
      apiHash: String(api.pluginConfig?.apiHash || ""),
      phone: String(api.pluginConfig?.phone || ""),
      stateDir: api.pluginConfig?.stateDir ? String(api.pluginConfig.stateDir) : undefined,
      actionIntervalMs: Number(api.pluginConfig?.actionIntervalMs || 1200),
      defaultTimeoutMs: Number(api.pluginConfig?.defaultTimeoutMs || 30000),
    };
    this.root = stateRoot(this.config);
    this.sessionPath = join(this.root, "session.txt");
    this.flowsPath = join(this.root, "flows.json");
    this.historyPath = join(this.root, "history.jsonl");
    this.client = null;
    this.pendingAuth = null;
    this.queueTail = Promise.resolve();
    this.lastActionAt = 0;
  }

  assertConfigured() {
    if (!Number.isInteger(this.config.apiId) || this.config.apiId <= 0) throw new Error("tg-sgk plugin config apiId is missing or invalid");
    if (!this.config.apiHash) throw new Error("tg-sgk plugin config apiHash is missing");
    if (!this.config.phone) throw new Error("tg-sgk plugin config phone is missing");
  }

  async initialize() {
    this.assertConfigured();
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    if (!existsSync(this.flowsPath)) await atomicWrite(this.flowsPath, "{}\n");
  }

  async readSession() {
    try {
      return (await readFile(this.sessionPath, "utf8")).trim();
    } catch (error) {
      if (error?.code === "ENOENT") return "";
      throw error;
    }
  }

  async saveSession(client) {
    const session = String(client.session.save());
    if (!session) throw new Error("Telegram returned an empty session");
    await atomicWrite(this.sessionPath, `${session}\n`);
  }

  createClient(session = "") {
    return new TelegramClient(new StringSession(session), this.config.apiId, this.config.apiHash, {
      connectionRetries: 5,
      autoReconnect: true,
      sequentialUpdates: true,
    });
  }

  async getAuthorizedClient() {
    await this.initialize();
    if (this.client) {
      try {
        if (!this.client.connected) await this.client.connect();
        if (await this.client.isUserAuthorized()) return this.client;
      } catch {
        try { await this.client.disconnect(); } catch {}
        this.client = null;
      }
    }
    const session = await this.readSession();
    if (!session) {
      const error = new Error("Telegram is not authorized. Run tg_auth_send_code first.");
      error.code = "AUTH_REQUIRED";
      throw error;
    }
    const client = this.createClient(session);
    await client.connect();
    if (!(await client.isUserAuthorized())) {
      await client.disconnect();
      const error = new Error("Saved Telegram session is no longer authorized. Run tg_auth_send_code again.");
      error.code = "AUTH_REQUIRED";
      throw error;
    }
    this.client = client;
    return client;
  }

  async authStatus() {
    await this.initialize();
    const hasSession = Boolean(await this.readSession());
    if (!hasSession) return { authorized: false, stage: this.pendingAuth?.stage || "not_started" };
    try {
      const client = await this.getAuthorizedClient();
      const me = await client.getMe();
      return { authorized: true, id: jsonSafe(me?.id), username: me?.username || null, phone: me?.phone || null };
    } catch (error) {
      return { authorized: false, stage: this.pendingAuth?.stage || "session_invalid", error: safeError(error) };
    }
  }

  async beginAuth() {
    await this.initialize();
    if (this.pendingAuth?.loginPromise) return { ok: true, stage: this.pendingAuth.stage, message: "Authorization is already in progress." };
    const client = this.createClient("");
    const pending = { client, stage: "connecting", codeResolve: null, passwordResolve: null, error: null, authorized: false, loginPromise: null };
    this.pendingAuth = pending;
    const waitForInput = (kind) => new Promise((resolve) => {
      if (kind === "code") {
        pending.stage = "code_sent";
        pending.codeResolve = resolve;
      } else {
        pending.stage = "password_required";
        pending.passwordResolve = resolve;
      }
    });
    pending.loginPromise = client.start({
      phoneNumber: async () => this.config.phone,
      phoneCode: async () => waitForInput("code"),
      password: async () => waitForInput("password"),
      onError: (error) => {
        pending.error = error;
        this.api.logger?.warn?.(`tg-sgk authorization error: ${error?.message || error}`);
      },
    }).then(async () => {
      await this.saveSession(client);
      pending.authorized = true;
      pending.stage = "authorized";
      this.client = client;
      return true;
    }).catch((error) => {
      pending.error = error;
      pending.stage = "failed";
      return false;
    });
    const deadline = Date.now() + 20000;
    while (pending.stage === "connecting" && Date.now() < deadline) await sleep(100);
    if (pending.stage === "failed") throw pending.error;
    if (pending.stage === "connecting") throw new Error("Timed out while requesting Telegram login code");
    return {
      ok: true,
      stage: pending.stage,
      phone: this.config.phone.replace(/.(?=.{4})/g, "*"),
      message: "Telegram login code was requested. Submit it with tg_auth_submit_code.",
    };
  }

  async settleAuth(timeoutMs = 20000) {
    const pending = this.pendingAuth;
    if (!pending) throw new Error("No authorization is in progress. Run tg_auth_send_code first.");
    const deadline = Date.now() + timeoutMs;
    while (!pending.authorized && pending.stage !== "password_required" && pending.stage !== "failed" && Date.now() < deadline) await sleep(100);
    if (pending.stage === "failed") throw pending.error;
    if (pending.authorized) {
      const me = await pending.client.getMe();
      this.pendingAuth = null;
      return { authorized: true, id: jsonSafe(me?.id), username: me?.username || null };
    }
    if (pending.stage === "password_required") return { authorized: false, passwordRequired: true, message: "Telegram 2FA password is required." };
    return { authorized: false, pending: true, stage: pending.stage };
  }

  async submitCode(code) {
    const pending = this.pendingAuth;
    if (!pending?.codeResolve) throw new Error("No login code is currently expected. Run tg_auth_send_code first.");
    const resolve = pending.codeResolve;
    pending.codeResolve = null;
    pending.stage = "verifying_code";
    resolve(String(code).trim());
    return this.settleAuth();
  }

  async submitPassword(password) {
    const pending = this.pendingAuth;
    if (!pending?.passwordResolve) throw new Error("Telegram is not currently waiting for a 2FA password.");
    const resolve = pending.passwordResolve;
    pending.passwordResolve = null;
    pending.stage = "verifying_password";
    resolve(String(password));
    return this.settleAuth();
  }

  enqueue(task, target, fn) {
    const run = async () => {
      const startedAt = new Date().toISOString();
      try {
        const elapsed = Date.now() - this.lastActionAt;
        if (elapsed < this.config.actionIntervalMs) await sleep(this.config.actionIntervalMs - elapsed);
        const result = await fn();
        this.lastActionAt = Date.now();
        await this.recordHistory({ task, target, status: "success", startedAt, finishedAt: new Date().toISOString() });
        return result;
      } catch (error) {
        await this.recordHistory({ task, target, status: "failed", error: safeError(error), startedAt, finishedAt: new Date().toISOString() });
        throw error;
      }
    };
    const result = this.queueTail.then(run, run);
    this.queueTail = result.catch(() => undefined);
    return result;
  }

  async recordHistory(entry) {
    await this.initialize();
    await appendFile(this.historyPath, `${JSON.stringify(entry)}\n`, { encoding: "utf8", mode: 0o600 });
  }

  async resolveBot(client, bot) {
    const target = normalizeBot(bot);
    const entity = await client.getEntity(target);
    if (!entity || entity.bot !== true) {
      const error = new Error(`Target ${target} is not a Telegram bot. Humans, groups, and channels are blocked.`);
      error.code = "TARGET_IS_NOT_A_BOT";
      throw error;
    }
    return { target, entity };
  }

  serializeEntity(target, entity) {
    return { target, isBot: entity?.bot === true, id: jsonSafe(entity?.id), username: entity?.username || null, firstName: entity?.firstName || null, lastName: entity?.lastName || null, verified: Boolean(entity?.verified) };
  }

  serializeMessage(message) {
    const rows = Array.isArray(message?.buttons) ? message.buttons : [];
    const buttons = [];
    rows.forEach((row, rowIndex) => {
      if (!Array.isArray(row)) return;
      row.forEach((button, columnIndex) => buttons.push({ row: rowIndex, column: columnIndex, text: button?.text || button?.button?.text || "", type: button?.button?.className || button?.constructor?.name || null }));
    });
    return {
      id: Number(message?.id),
      text: message?.message || message?.text || "",
      outgoing: Boolean(message?.out),
      date: message?.date instanceof Date ? message.date.toISOString() : message?.date || null,
      editDate: message?.editDate instanceof Date ? message.editDate.toISOString() : message?.editDate || null,
      buttons,
    };
  }

  inspect(bot) {
    return this.enqueue("inspect_bot", bot, async () => {
      const client = await this.getAuthorizedClient();
      const { target, entity } = await this.resolveBot(client, bot);
      return this.serializeEntity(target, entity);
    });
  }

  sendMessage(bot, text) {
    return this.enqueue("send_message", bot, async () => {
      const client = await this.getAuthorizedClient();
      const { target, entity } = await this.resolveBot(client, bot);
      const message = await client.sendMessage(entity, { message: String(text) });
      return { bot: this.serializeEntity(target, entity), message: this.serializeMessage(message) };
    });
  }

  recentMessages(bot, limit = 10) {
    return this.enqueue("recent_messages", bot, async () => {
      const client = await this.getAuthorizedClient();
      const { target, entity } = await this.resolveBot(client, bot);
      const messages = await client.getMessages(entity, { limit: Math.max(1, Math.min(50, Number(limit) || 10)) });
      return { bot: target, messages: Array.from(messages || []).map((message) => this.serializeMessage(message)) };
    });
  }

  waitUpdate(bot, options = {}) {
    return this.enqueue("wait_update", bot, async () => {
      const timeoutMs = Math.min(120000, Math.max(1000, Number(options.timeoutSeconds || 30) * 1000));
      const deadline = Date.now() + timeoutMs;
      const afterId = Number(options.afterMessageId || 0);
      const watchId = Number(options.watchMessageId || 0);
      const previousSignature = String(options.previousSignature || "");
      while (Date.now() < deadline) {
        const client = await this.getAuthorizedClient();
        const { target, entity } = await this.resolveBot(client, bot);
        const serialized = Array.from(await client.getMessages(entity, { limit: 15 }) || []).map((message) => this.serializeMessage(message));
        const newer = serialized.find((message) => message.id > afterId && !message.outgoing);
        if (newer) return { bot: target, kind: "new_message", message: newer };
        if (watchId) {
          const watched = serialized.find((message) => message.id === watchId);
          if (watched) {
            const signature = JSON.stringify({ text: watched.text, buttons: watched.buttons, editDate: watched.editDate });
            if (previousSignature && signature !== previousSignature) return { bot: target, kind: "edited_message", message: watched, signature };
          }
        }
        await sleep(800);
      }
      return { bot: normalizeBot(bot), kind: "timeout", timeoutMs };
    });
  }

  clickButton(bot, params) {
    return this.enqueue("click_button", bot, async () => {
      const client = await this.getAuthorizedClient();
      const { target, entity } = await this.resolveBot(client, bot);
      const messages = Array.from(await client.getMessages(entity, { ids: Number(params.messageId) }) || []);
      const message = messages[0];
      if (!message) throw new Error(`Message ${params.messageId} was not found in ${target}`);
      let response;
      if (params.text) response = await message.click({ text: String(params.text) });
      else {
        if (!Number.isInteger(params.row) || !Number.isInteger(params.column)) throw new Error("Provide either exact button text or both row and column");
        response = await message.click({ i: Number(params.row), j: Number(params.column) });
      }
      await sleep(500);
      const recent = Array.from(await client.getMessages(entity, { limit: 5 }) || []).map((item) => this.serializeMessage(item));
      return { bot: target, clicked: { messageId: Number(params.messageId), text: params.text || null, row: params.row ?? null, column: params.column ?? null }, response: response ? String(response) : null, recent };
    });
  }

  async readFlows() {
    await this.initialize();
    try { return JSON.parse(await readFile(this.flowsPath, "utf8")); } catch { return {}; }
  }

  async saveFlow(flow) {
    const flows = await this.readFlows();
    flows[flow.id] = { ...flow, updatedAt: new Date().toISOString() };
    await atomicWrite(this.flowsPath, `${JSON.stringify(flows, null, 2)}\n`);
    return flows[flow.id];
  }

  async listFlows() {
    return Object.values(await this.readFlows());
  }

  async runFlow(flowId) {
    const flows = await this.readFlows();
    const flow = flows[flowId];
    if (!flow) throw new Error(`Flow not found: ${flowId}`);
    return this.enqueue("run_flow", flow.bot, async () => {
      const results = [];
      let latestMessages = [];
      for (const [index, step] of flow.steps.entries()) {
        let result;
        if (step.action === "send_message") {
          const client = await this.getAuthorizedClient();
          const { entity } = await this.resolveBot(client, flow.bot);
          result = this.serializeMessage(await client.sendMessage(entity, { message: String(step.text || "") }));
        } else if (step.action === "sleep") {
          await sleep(Math.max(0, Number(step.seconds || 1)) * 1000);
          result = { sleptSeconds: Number(step.seconds || 1) };
        } else if (step.action === "wait_message" || step.action === "wait_message_or_edit") {
          await sleep(Math.min(5000, Math.max(500, Number(step.timeout_seconds || 2) * 1000)));
          const client = await this.getAuthorizedClient();
          const { entity } = await this.resolveBot(client, flow.bot);
          latestMessages = Array.from(await client.getMessages(entity, { limit: 10 }) || []).map((item) => this.serializeMessage(item));
          result = { messages: latestMessages };
        } else if (step.action === "click_button") {
          const client = await this.getAuthorizedClient();
          const { entity } = await this.resolveBot(client, flow.bot);
          const messages = Array.from(await client.getMessages(entity, { limit: 10 }) || []);
          const message = messages.find((item) => {
            const buttons = this.serializeMessage(item).buttons;
            return step.text ? buttons.some((button) => button.text === step.text) : buttons.length > 0;
          });
          if (!message) throw new Error(`Flow step ${index + 1}: no matching button message found`);
          result = step.text ? await message.click({ text: String(step.text) }) : await message.click({ i: Number(step.row || 0), j: Number(step.column || 0) });
        } else if (step.action === "assert_text") {
          if (!latestMessages.length) {
            const client = await this.getAuthorizedClient();
            const { entity } = await this.resolveBot(client, flow.bot);
            latestMessages = Array.from(await client.getMessages(entity, { limit: 10 }) || []).map((item) => this.serializeMessage(item));
          }
          const haystack = latestMessages.map((item) => item.text).join("\n");
          const expected = Array.isArray(step.contains_any) ? step.contains_any : [];
          if (!expected.some((value) => haystack.includes(String(value)))) throw new Error(`Flow assertion failed; expected one of: ${expected.join(", ")}`);
          result = { matched: expected.find((value) => haystack.includes(String(value))) };
        } else throw new Error(`Unsupported flow action: ${step.action}`);
        results.push({ index, action: step.action, result: jsonSafe(result) });
      }
      return { flowId, bot: flow.bot, results };
    });
  }

  async history(limit = 50, target) {
    await this.initialize();
    try {
      const lines = (await readFile(this.historyPath, "utf8")).trim().split("\n").filter(Boolean);
      return lines.map((line) => JSON.parse(line)).filter((entry) => !target || entry.target === target).slice(-Math.max(1, Math.min(200, Number(limit) || 50))).reverse();
    } catch (error) {
      if (error?.code === "ENOENT") return [];
      throw error;
    }
  }
}

const configSchema = Type.Object({
  apiId: Type.Integer({ minimum: 1, description: "Telegram api_id from my.telegram.org" }),
  apiHash: Type.String({ minLength: 8, description: "Telegram api_hash from my.telegram.org" }),
  phone: Type.String({ minLength: 5, description: "Telegram phone number with country code" }),
  stateDir: Type.Optional(Type.String({ minLength: 1 })),
  actionIntervalMs: Type.Optional(Type.Integer({ minimum: 0, maximum: 60000, default: 1200 })),
  defaultTimeoutMs: Type.Optional(Type.Integer({ minimum: 1000, maximum: 180000, default: 30000 })),
}, { additionalProperties: false });

const flowStepSchema = Type.Object({
  action: Type.Union([Type.Literal("send_message"), Type.Literal("wait_message"), Type.Literal("click_button"), Type.Literal("wait_message_or_edit"), Type.Literal("sleep"), Type.Literal("assert_text")]),
  text: Type.Optional(Type.String()),
  row: Type.Optional(Type.Integer({ minimum: 0 })),
  column: Type.Optional(Type.Integer({ minimum: 0 })),
  timeout_seconds: Type.Optional(Type.Number({ minimum: 0.1, maximum: 120 })),
  seconds: Type.Optional(Type.Number({ minimum: 0, maximum: 60 })),
  contains_any: Type.Optional(Type.Array(Type.String(), { minItems: 1 })),
}, { additionalProperties: false });

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "TG SGK",
  description: "Direct Telegram user-account automation for bot chats only. No Docker sidecar required.",
  configSchema,
  register(api) {
    const runtime = new TgSgkRuntime(api);
    const register = (definition) => api.registerTool({
      ...definition,
      async execute(_toolCallId, params) {
        try { return textResult(await definition.run(params || {})); }
        catch (error) {
          const normalized = safeError(error);
          api.logger?.error?.(`tg-sgk ${definition.name} failed: ${normalized.message}`);
          throw new Error(`${normalized.code ? `${normalized.code}: ` : ""}${normalized.message}`);
        }
      },
    });

    register({ name: "tg_auth_status", description: "Check whether the Telegram user account is authorized.", parameters: Type.Object({}), run: () => runtime.authStatus() });
    register({ name: "tg_auth_send_code", description: "Start Telegram user authorization and request a login code. Call this once, then ask the operator for the code.", parameters: Type.Object({}), run: () => runtime.beginAuth() });
    register({ name: "tg_auth_submit_code", description: "Submit the Telegram login code received by the operator. Never guess a code.", parameters: Type.Object({ code: Type.String({ minLength: 3, maxLength: 20 }) }), run: ({ code }) => runtime.submitCode(code) });
    register({ name: "tg_auth_submit_password", description: "Submit the Telegram two-factor password only when tg_auth_submit_code reports passwordRequired=true.", parameters: Type.Object({ password: Type.String({ minLength: 1, maxLength: 256 }) }), run: ({ password }) => runtime.submitPassword(password) });
    register({ name: "tg_bot_inspect", description: "Resolve a Telegram username and verify it is a bot. Humans, groups, and channels are rejected.", parameters: Type.Object({ bot: Type.String({ minLength: 2 }) }), run: ({ bot }) => runtime.inspect(bot) });
    register({ name: "tg_send_message", description: "Send text or a command to a verified Telegram bot.", parameters: Type.Object({ bot: Type.String({ minLength: 2 }), text: Type.String({ minLength: 1, maxLength: 4096 }) }), run: ({ bot, text }) => runtime.sendMessage(bot, text) });
    register({ name: "tg_get_recent_messages", description: "Read recent messages and button layouts from a verified Telegram bot.", parameters: Type.Object({ bot: Type.String({ minLength: 2 }), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })) }), run: ({ bot, limit }) => runtime.recentMessages(bot, limit) });
    register({ name: "tg_wait_update", description: "Poll a verified Telegram bot for a new message or an edited known message.", parameters: Type.Object({ bot: Type.String({ minLength: 2 }), afterMessageId: Type.Optional(Type.Integer()), watchMessageId: Type.Optional(Type.Integer()), previousSignature: Type.Optional(Type.String()), timeoutSeconds: Type.Optional(Type.Number({ minimum: 1, maximum: 120 })) }), run: ({ bot, ...options }) => runtime.waitUpdate(bot, options) });
    register({ name: "tg_click_button", description: "Click a button in a verified Telegram bot message by exact text or row and column.", parameters: Type.Object({ bot: Type.String({ minLength: 2 }), messageId: Type.Integer(), text: Type.Optional(Type.String({ minLength: 1 })), row: Type.Optional(Type.Integer({ minimum: 0 })), column: Type.Optional(Type.Integer({ minimum: 0 })) }), run: ({ bot, ...params }) => runtime.clickButton(bot, params) });
    register({ name: "tg_save_flow", description: "Save or replace a confirmed fixed workflow for a Telegram bot.", parameters: Type.Object({ id: Type.String({ minLength: 2, maxLength: 64 }), name: Type.String({ minLength: 1, maxLength: 128 }), bot: Type.String({ minLength: 2 }), steps: Type.Array(flowStepSchema, { minItems: 1, maxItems: 50 }) }), run: (flow) => runtime.saveFlow(flow) });
    register({ name: "tg_list_flows", description: "List saved Telegram bot workflows.", parameters: Type.Object({}), run: () => runtime.listFlows() });
    register({ name: "tg_run_flow", description: "Run one saved Telegram bot workflow without model reasoning for each step.", parameters: Type.Object({ flowId: Type.String({ minLength: 2, maxLength: 64 }) }), run: ({ flowId }) => runtime.runFlow(flowId) });
    register({ name: "tg_get_history", description: "Read local execution history for diagnosis.", parameters: Type.Object({ limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })), target: Type.Optional(Type.String()) }), run: ({ limit, target }) => runtime.history(limit, target) });
  },
});
