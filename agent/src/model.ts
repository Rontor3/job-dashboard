// The agent's model: whatever the config table names (LLM_BASE_URL, LLM_MODEL, LLM_CONTEXT_WINDOW), through pi-ai's
// OpenAI-compatible Responses API. This is the one exception to "every model call goes through llm.py" (ADR 0001).
// Nothing here is tied to one model: the provider is rebuilt when the config changes, and each session runs with
// the model it is configured with.
import { createModels, createProvider, type Model } from "@earendil-works/pi-ai";
import type { MutableModels } from "@earendil-works/pi-ai/models";
import { openAIResponsesApi } from "@earendil-works/pi-ai/api/openai-responses.lazy";
import type { ApiClient } from "./api.ts";
import { setting } from "./env.ts";

export const PROVIDER = "jobdash-llm";
const DEFAULT_BASE_URL = "http://localhost:11434/v1";
const DEFAULT_MODEL = "qwen3:14b";
const DEFAULT_CONTEXT = 131_072;

export interface LlmSettings {
  baseUrl: string;
  modelId: string;
  contextWindow: number;
  /** The thinking level a session starts with: LLM_REASONING_EFFORT (none = off), else medium. */
  thinkingLevel: string;
  /** Pasted pictures reach the model unless the endpoint can't take them (LLM_IMAGES=0). */
  images?: boolean;
}

const EFFORT_TO_LEVEL: Record<string, string> = { none: "off", low: "low", medium: "medium", high: "high", xhigh: "xhigh" };

export async function readLlmSettings(client: ApiClient): Promise<LlmSettings> {
  const rows = ((await client.get("/api/config")) as { config: { key: string; value: string | null }[] }).config;
  const value = (k: string) => rows.find((r) => r.key === k)?.value ?? undefined;
  return {
    baseUrl: (value("LLM_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/$/, ""),
    modelId: value("LLM_MODEL") ?? setting("OLLAMA_MODEL") ?? DEFAULT_MODEL,
    contextWindow: Number(value("LLM_CONTEXT_WINDOW") ?? DEFAULT_CONTEXT),
    thinkingLevel: EFFORT_TO_LEVEL[(value("LLM_REASONING_EFFORT") ?? "").toLowerCase()] ?? "medium",
    images: value("LLM_IMAGES") !== "0",
  };
}

function modelFor(s: LlmSettings): Model<"openai-responses"> {
  return {
    id: s.modelId,
    name: s.modelId,
    api: "openai-responses",
    provider: PROVIDER,
    baseUrl: s.baseUrl,
    reasoning: true,                       // /thinking sends reasoning.effort; "off" sends effort "none"
    thinkingLevelMap: { minimal: null },   // not an OpenAI effort; the endpoint answers for the rest
    input: s.images === false ? ["text"] : ["text", "image"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: s.contextWindow,
    maxTokens: 8192,
  };
}

export type ModelRef = { provider: string; modelId: string };

/** Where sessions get their model: the config table in production, a scripted faux model in tests. */
export interface ModelSource {
  readonly models: MutableModels;
  sync(client: ApiClient): Promise<ModelRef>;
  /** Offer more model ids (for /model); the faux source in tests ignores this. */
  offer?(client: ApiClient, ...ids: string[]): Promise<void>;
  available?(client: ApiClient): Promise<string[]>;
  readonly settings?: LlmSettings;
}

/** The catalog the harness uses, kept in step with the config table. Besides the configured model it offers any
 * model a session picked with /model on the same endpoint. */
export class LiveModels implements ModelSource {
  readonly models: MutableModels;
  private current?: LlmSettings;
  private offered = "";
  private extra = new Set<string>();

  constructor(models: MutableModels = createModels()) {
    this.models = models;
  }

  get settings(): LlmSettings | undefined {
    return this.current;
  }

  /** Offer another model id on the configured endpoint (for /model). */
  async offer(client: ApiClient, ...ids: string[]): Promise<void> {
    for (const id of ids) this.extra.add(id);
    await this.sync(client);
  }

  /** Re-read the config; rebuild the provider if it changed. Returns the model ref sessions should run with. */
  async sync(client: ApiClient): Promise<ModelRef> {
    const s = await readLlmSettings(client);
    const ids = [s.modelId, ...[...this.extra].filter((id) => id !== s.modelId)];
    const key = JSON.stringify([s, ids]);
    if (key !== this.offered) {
      this.models.setProvider(createProvider({
        id: PROVIDER,
        name: "Configured LLM endpoint",
        baseUrl: s.baseUrl,
        // The key is read from .env on every request, so setting it from the dashboard applies at once. A keyless
        // endpoint still needs some key here, or the Responses API refuses to send.
        auth: { apiKey: { name: "LLM_API_KEY", resolve: async () => ({ auth: { apiKey: setting("LLM_API_KEY") || "unused" } }) } },
        models: ids.map((id) => modelFor({ ...s, modelId: id })),
        api: openAIResponsesApi(),
      }));
      this.current = s;
      this.offered = key;
    }
    return { provider: PROVIDER, modelId: s.modelId };
  }

  /** The endpoint's own model list (OpenAI-compatible GET /models); empty if it has none. */
  async available(client: ApiClient): Promise<string[]> {
    const s = this.current ?? await readLlmSettings(client);
    try {
      const res = await fetch(`${s.baseUrl}/models`, {
        headers: { authorization: `Bearer ${setting("LLM_API_KEY") || "unused"}` },
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) return [];
      const body = await res.json() as { data?: { id?: string }[]; models?: { name?: string }[] };
      return (body.data?.map((m) => m.id) ?? body.models?.map((m) => m.name) ?? []).filter((x): x is string => !!x).sort();
    } catch {
      return [];
    }
  }
}
