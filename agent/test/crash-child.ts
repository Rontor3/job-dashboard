// Run by e2e.test.ts in its own process: start a run whose replay-safe write tool dies right after FastAPI applied
// the write, before Pi Durable committed the tool's result. The test then reopens the store and resumes.
//   node crash-child.ts <db file> <api url> <entry id>
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { createModels, fauxAssistantMessage, fauxProvider, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { createRegistry, defineExtension, Harness, wrapTool } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { apiClient } from "../src/api.ts";
import { makeTools } from "../src/tools.ts";

const [dbFile, apiUrl, entryId] = process.argv.slice(2) as [string, string, string];
const ctx = BACKGROUND_CONTEXT;
const faux = fauxProvider();
const models = createModels();
models.setProvider(faux.provider);
const model = faux.getModel();
faux.setResponses([
  fauxAssistantMessage([fauxToolCall("set_answer", { entry_id: entryId, answer: "8.30/10" })], { stopReason: "toolUse" }),
  fauxAssistantMessage([fauxText("Saved.")]),
]);
const tools = makeTools(apiClient(apiUrl));
const setAnswer = tools.find((t) => t.name === "set_answer")!;
const registry = createRegistry();
registry.install(defineExtension({ name: "jobdash", tools }));
registry.install(defineExtension({
  name: "crash",
  wraps: [wrapTool(setAnswer, (tool) => ({
    ...tool,
    execute: async (args, api, context) => {
      await tool.execute(args, api, context);
      process.exit(137);                         // die after the write, before the result is committed
    },
  }))],
}));
const harness = await Harness.open(await openNodeSqliteStorage(dbFile), { models, registry }, ctx);
const conv = await harness.createConversation({ ownership: { kind: "ownerless" }, agent: { model: { provider: model.provider, modelId: model.id } } }, ctx);
console.log(`conversation-${conv.id}`);              // its session key: this test makes no session list
const sub = await conv.submit({ type: "input", content: "Save 8.30/10 as my CGPA answer.", requestId: "crash-1" }, ctx);
await sub.wait(ctx);
