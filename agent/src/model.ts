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
}

export async function readLlmSettings(client: ApiClient): Promise<LlmSettings> {
  const rows = ((await client.get("/api/config")) as { config: { key: string; value: string | null }[] }).config;
  const value = (k: string) => rows.find((r) => r.key === k)?.value ?? undefined;
  return {
    baseUrl: (value("LLM_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/$/, ""),
    modelId: value("LLM_MODEL") ?? setting("OLLAMA_MODEL") ?? DEFAULT_MODEL,
    contextWindow: Number(value("LLM_CONTEXT_WINDOW") ?? DEFAULT_CONTEXT),
  };
}

function modelFor(s: LlmSettings): Model<"openai-responses"> {
  return {
    id: s.modelId,
    name: s.modelId,
    api: "openai-responses",
    provider: PROVIDER,
    baseUrl: s.baseUrl,
    reasoning: false,                      // reasoning models still stream thinking; the UI folds it away
    input: ["text"],
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
}

/** The catalog the harness uses, kept in step with the config table. */
export class LiveModels implements ModelSource {
  readonly models: MutableModels;
  private current?: LlmSettings;

  constructor(models: MutableModels = createModels()) {
    this.models = models;
  }

  /** Re-read the config; rebuild the provider if it changed. Returns the model ref sessions should run with. */
  async sync(client: ApiClient): Promise<ModelRef> {
    const s = await readLlmSettings(client);
    if (JSON.stringify(s) !== JSON.stringify(this.current)) {
      this.models.setProvider(createProvider({
        id: PROVIDER,
        name: "Configured LLM endpoint",
        baseUrl: s.baseUrl,
        // The key is read from .env on every request, so setting it from the dashboard applies at once. A keyless
        // endpoint still needs some key here, or the Responses API refuses to send.
        auth: { apiKey: { name: "LLM_API_KEY", resolve: async () => ({ auth: { apiKey: setting("LLM_API_KEY") || "unused" } }) } },
        models: [modelFor(s)],
        api: openAIResponsesApi(),
      }));
      this.current = s;
    }
    return { provider: PROVIDER, modelId: s.modelId };
  }
}
