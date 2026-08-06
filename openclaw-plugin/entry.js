import { mkdirSync, readFileSync, writeFileSync, renameSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Type } from "typebox";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import corePlugin from "./index.js";

const PLUGIN_ID = "tg-sgk";

function rootFor(config = {}) {
  const base = process.env.OPENCLAW_STATE_DIR || join(homedir(), ".openclaw");
  return config.stateDir || join(base, "tg-sgk");
}

function credentialsPath(config = {}) {
  return join(rootFor(config), "credentials.json");
}

function readSaved(config = {}) {
  try {
    return JSON.parse(readFileSync(credentialsPath(config), "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw error;
  }
}

function normalizeCredentials(raw = {}) {
  return {
    apiId: Number(raw.apiId),
    apiHash: String(raw.apiHash || "").trim(),
    phone: String(raw.phone || "").trim(),
  };
}

function validCredentials(value) {
  return Number.isInteger(value.apiId)
    && value.apiId > 0
    && value.apiHash.length >= 8
    && value.phone.length >= 5;
}

function mergedCredentials(config = {}) {
  const saved = readSaved(config);
  return normalizeCredentials({
    apiId: config.apiId || saved.apiId,
    apiHash: config.apiHash || saved.apiHash,
    phone: config.phone || saved.phone,
  });
}

function saveCredentials(config, params) {
  const credentials = normalizeCredentials(params);
  if (!validCredentials(credentials)) {
    throw new Error("Invalid Telegram credentials: apiId, apiHash, and phone are required.");
  }
  const root = rootFor(config);
  mkdirSync(root, { recursive: true, mode: 0o700 });
  const path = credentialsPath(config);
  const temporary = `${path}.tmp-${process.pid}-${Date.now()}`;
  writeFileSync(temporary, `${JSON.stringify(credentials, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  renameSync(temporary, path);
  return credentials;
}

const output = (data) => ({
  content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
  details: data,
});

const configSchema = Type.Object({
  apiId: Type.Optional(Type.Integer({ minimum: 1 })),
  apiHash: Type.Optional(Type.String({ minLength: 8 })),
  phone: Type.Optional(Type.String({ minLength: 5 })),
  stateDir: Type.Optional(Type.String({ minLength: 1 })),
  actionIntervalMs: Type.Optional(Type.Integer({ minimum: 0, maximum: 60000, default: 1200 })),
  defaultTimeoutMs: Type.Optional(Type.Integer({ minimum: 1000, maximum: 180000, default: 30000 })),
}, { additionalProperties: false });

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "TG SGK",
  description: "Direct Telegram user-account automation for verified bot chats only.",
  configSchema,
  register(api) {
    const baseConfig = api.pluginConfig || {};
    let runtimeFingerprint = "";
    let runtimeTools = new Map();

    const buildRuntime = (credentials) => {
      const fingerprint = JSON.stringify(credentials);
      if (fingerprint === runtimeFingerprint && runtimeTools.size) return runtimeTools;
      const collected = new Map();
      corePlugin.register({
        ...api,
        pluginConfig: { ...baseConfig, ...credentials, stateDir: rootFor(baseConfig) },
        registerTool(tool) { collected.set(tool.name, tool); },
      });
      runtimeFingerprint = fingerprint;
      runtimeTools = collected;
      return runtimeTools;
    };

    const currentCredentials = mergedCredentials(baseConfig);
    const metadataCredentials = validCredentials(currentCredentials)
      ? currentCredentials
      : { apiId: 1, apiHash: "placeholder-api-hash", phone: "+10000000000" };
    const metadataTools = buildRuntime(metadataCredentials);
    runtimeFingerprint = "";
    runtimeTools = new Map();

    api.registerTool({
      name: "tg_setup_credentials",
      description: "Save Telegram api_id, api_hash, and phone locally for this OpenClaw instance.",
      parameters: Type.Object({
        apiId: Type.Integer({ minimum: 1 }),
        apiHash: Type.String({ minLength: 8 }),
        phone: Type.String({ minLength: 5 }),
      }),
      async execute(_id, params) {
        const credentials = saveCredentials(baseConfig, params || {});
        runtimeFingerprint = "";
        runtimeTools = new Map();
        return output({
          configured: true,
          apiId: credentials.apiId,
          phone: credentials.phone.replace(/.(?=.{4})/g, "*"),
          next: "Run tg_auth_send_code.",
        });
      },
    });

    for (const metadata of metadataTools.values()) {
      api.registerTool({
        name: metadata.name,
        description: metadata.description,
        parameters: metadata.parameters,
        async execute(toolCallId, params, context) {
          const credentials = mergedCredentials(baseConfig);
          if (!validCredentials(credentials)) {
            if (metadata.name === "tg_auth_status") {
              return output({
                configured: false,
                authorized: false,
                stage: "credentials_required",
                next: "Run tg_setup_credentials.",
              });
            }
            throw new Error("CREDENTIALS_REQUIRED: Run tg_setup_credentials first.");
          }
          const tool = buildRuntime(credentials).get(metadata.name);
          if (!tool) throw new Error(`Runtime tool not found: ${metadata.name}`);
          return tool.execute(toolCallId, params, context);
        },
      });
    }
  },
});
