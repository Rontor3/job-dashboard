// The agent service's HTTP surface (Hono). The user sees one address: this service answers /agent/*, passes
// /api/* through to FastAPI, and in production serves the built dashboard.
//
//   GET  /agent/sessions                     the session list and which one is active
//   POST /agent/sessions                     {profile?} start a new session (it becomes active)
//   POST /agent/sessions/:id/activate        reopen a past session
//   GET  /agent/sessions/:id/events          SSE: a snapshot, then agent events (any number of clients)
//   POST /agent/sessions/:id/messages        {content, requestId, context?, images?} — exactly once per requestId
//   POST /agent/sessions/:id/stop            abort the running work
//   …and the slash commands (commands.ts)
import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize, sep } from "node:path";
import type { Context } from "@earendil-works/chord";
import { watchEvents, type Conversation, type Harness } from "@earendil-works/pi-durable";
import { encodeElementMessage, type ElementContext } from "@jobdash/agent-protocol";
import { Hono } from "hono";
import { streamSSE } from "hono/streaming";
import type { ApiClient } from "./api.ts";
import type { ModelSource } from "./model.ts";
import { installCommands } from "./commands.ts";
import { applyProfile, findProfile } from "./team.ts";
import { activate, conversationOf, createSession, ensureActive, nameIfNew, sessionItem, sessionsState } from "./sessions.ts";

export interface AgentDeps {
  harness: Harness;
  client: ApiClient;
  live: ModelSource;
  ctx: Context;
  /** Built dashboard to serve (production); undefined in development, where Vite serves it. */
  staticDir?: string;
  /** How often an idle event stream sends a keep-alive comment. */
  heartbeatMs?: number;
  /** /reload: re-install the extension from disk; returns what was loaded. */
  reload?: () => Promise<string[]>;
}

const MAX_MESSAGE = 20_000;
// Pasted or attached pictures: a few, of the kinds every vision model reads, each under ~5 MB.
const MAX_IMAGES = 4;
const MAX_IMAGE_B64 = 7_000_000;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
type ImageIn = { type: "image"; data: string; mimeType: string };

/** The valid images in a request body, or a reason to refuse it. */
function images(raw: unknown): ImageIn[] | string {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length > MAX_IMAGES) return `at most ${MAX_IMAGES} images`;
  const out: ImageIn[] = [];
  for (const i of raw as { data?: unknown; mimeType?: unknown }[]) {
    if (typeof i?.data !== "string" || typeof i.mimeType !== "string" || !IMAGE_TYPES.has(i.mimeType)) return "images must be PNG, JPEG, WebP or GIF";
    if (i.data.length > MAX_IMAGE_B64 || !/^[A-Za-z0-9+/=]+$/.test(i.data.slice(0, 200))) return "an image is too large or not base64";
    out.push({ type: "image", data: i.data, mimeType: i.mimeType });
  }
  return out;
}
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
  ".woff": "font/woff", ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
};

export function createAgentApp(deps: AgentDeps): Hono {
  const { harness, client, live, ctx } = deps;
  const app = new Hono();
  const configured = new Map<string, string>();         // conversation id -> model id it runs with

  /** The session, running on its model: one picked with /model, else the configured one (which can change
   * between messages). */
  async function session(key: string): Promise<Conversation | undefined> {
    const conv = await conversationOf(harness, key, ctx);
    if (!conv) return undefined;
    const app = await live.sync(client);
    const pinned = (await sessionItem(harness, key, ctx))?.model;
    if (pinned) await live.offer?.(client, pinned);
    const model = pinned ? { provider: app.provider, modelId: pinned } : app;
    if (configured.get(key) !== model.modelId) {
      // A session that never chose a thinking level starts at the app's (LLM_REASONING_EFFORT, else medium).
      const level = live.settings?.thinkingLevel;
      const chosen = level && configured.has(key) ? true : await hasThinkingLevel(conv);
      await conv.configure({ model, ...(chosen || !level ? {} : { thinkingLevel: level as never }) }, ctx);
      configured.set(key, model.modelId);
    }
    return conv;
  }

  async function hasThinkingLevel(conv: Conversation): Promise<boolean> {
    const view = await conv.viewState(ctx);
    const level = (view.value as unknown as { docs: Record<string, { thinkingLevel?: string } | undefined> }).docs["pi.agent"]?.thinkingLevel;
    view.dispose();
    return level !== undefined;
  }

  async function submit(key: string, conv: Conversation, content: string, requestId: string, whenBusy?: "steer" | "followUp",
    pics: ImageIn[] = []) {
    const input = pics.length ? [{ type: "text" as const, text: content }, ...pics] : content;
    const sub = await conv.submit({ type: "input", content: input, requestId, ...(whenBusy ? { whenBusy } : {}) }, ctx);
    await nameIfNew(harness, key, content, ctx);
    return Number(sub.id);
  }

  installCommands(app, { harness, client, live, ctx, reload: deps.reload, session, submit });

  app.get("/agent/health", (c) => c.json({ ok: true }));

  app.get("/agent/sessions", async (c) => {
    if (!(await sessionsState(harness, ctx)).active) await ensureActive(harness, await live.sync(client), ctx);
    return c.json(await sessionsState(harness, ctx));
  });

  app.post("/agent/sessions", async (c) => {
    const body = await c.req.json().catch(() => ({})) as { profile?: unknown };
    const profile = typeof body.profile === "string" && body.profile !== "default" ? findProfile(body.profile) : undefined;
    if (typeof body.profile === "string" && body.profile !== "default" && !profile) return c.json({ detail: "no such profile" }, 404);
    const id = await createSession(harness, await live.sync(client), ctx, profile ? { profile: profile.name } : {});
    if (profile) await applyProfile((await conversationOf(harness, id, ctx))!, profile, ctx);
    return c.json({ id, ...(await sessionsState(harness, ctx)) });
  });

  app.post("/agent/sessions/:id/activate", async (c) => {
    if (!(await activate(harness, c.req.param("id"), ctx))) return c.json({ detail: "no such session" }, 404);
    return c.json(await sessionsState(harness, ctx));
  });

  app.get("/agent/sessions/:id/events", async (c) => {
    const conv = await conversationOf(harness, c.req.param("id"), ctx);
    if (!conv) return c.json({ detail: "no such session" }, 404);
    return streamSSE(c, async (sse) => {
      const stream = await watchEvents(harness, conv.id, ctx);
      let closed!: () => void;
      const done = new Promise<void>((r) => (closed = r));
      sse.onAbort(() => closed());
      await sse.writeSSE({ event: "agent", data: JSON.stringify(stream.snapshot) });
      stream.start(async (events) => {
        for (const e of events) await sse.writeSSE({ event: "agent", data: JSON.stringify(e) });
      });
      const beat = setInterval(() => void sse.write(": keep-alive\n\n").catch(() => closed()), deps.heartbeatMs ?? 25_000);
      await done;
      clearInterval(beat);
      await stream.stop?.();
    });
  });

  app.post("/agent/sessions/:id/messages", async (c) => {
    const body = await c.req.json().catch(() => null) as { content?: unknown; requestId?: unknown; context?: ElementContext; whenBusy?: unknown; images?: unknown } | null;
    const content = typeof body?.content === "string" ? body.content.trim() : "";
    const requestId = typeof body?.requestId === "string" ? body.requestId : "";
    if (!content || content.length > MAX_MESSAGE) return c.json({ detail: "content must be 1-20000 characters" }, 422);
    if (!requestId || requestId.length > 200) return c.json({ detail: "requestId is required" }, 422);
    const pics = images(body?.images);
    if (typeof pics === "string") return c.json({ detail: pics }, 422);
    const key = c.req.param("id");
    const conv = await session(key);
    if (!conv) return c.json({ detail: "no such session" }, 404);
    const text = encodeElementMessage(body?.context?.text !== undefined ? body.context : undefined, content);
    // pi's Enter while busy steers the current task; Alt+Enter queues a follow-up for after it.
    const whenBusy = body?.whenBusy === "steer" || body?.whenBusy === "followUp" ? body.whenBusy : undefined;
    return c.json({ submission: await submit(key, conv, text, requestId, whenBusy, pics) });
  });

  app.post("/agent/sessions/:id/stop", async (c) => {
    const conv = await conversationOf(harness, c.req.param("id"), ctx);
    if (!conv) return c.json({ detail: "no such session" }, 404);
    await conv.abort(ctx);
    return c.json({ stopped: true });
  });

  // Everything else under /api is FastAPI's.
  app.all("/api/*", async (c) => {
    const url = new URL(c.req.url);
    const headers = new Headers(c.req.raw.headers);
    headers.delete("host");
    const method = c.req.method;
    const init: RequestInit & { duplex?: "half" } = { method, headers, redirect: "manual" };
    if (method !== "GET" && method !== "HEAD") {
      init.body = c.req.raw.body;
      init.duplex = "half";
    }
    try {
      const res = await fetch(client.baseUrl + url.pathname + url.search, init);
      const out = new Headers(res.headers);
      for (const h of ["content-encoding", "content-length", "transfer-encoding", "connection"]) out.delete(h);
      return new Response(res.body, { status: res.status, headers: out });
    } catch {
      return c.json({ detail: "the api isn't answering" }, 502);
    }
  });

  if (deps.staticDir && existsSync(join(deps.staticDir, "index.html"))) {
    const root = deps.staticDir;
    app.get("*", (c) => {
      let rel = "";
      try {
        rel = normalize(decodeURIComponent(new URL(c.req.url).pathname)).replace(/^(\.\.[/\\])+/, "");
      } catch {
        // a malformed escape: serve the app
      }
      const file = join(root, rel);
      const hit = file.startsWith(root + sep) && existsSync(file) && extname(file) ? file : join(root, "index.html");
      return new Response(readFileSync(hit), {
        headers: {
          "content-type": TYPES[extname(hit)] ?? "application/octet-stream",
          // Vite hashes asset names, so those cache forever; index.html must always revalidate.
          "cache-control": hit.includes(`${join(root, "assets")}`) ? "public, max-age=31536000, immutable" : "no-cache",
        },
      });
    });
  }
  return app;
}
