// Sessions: one Pi Durable conversation each, one active at a time (spec Q8). The list and the active session live
// in a Session-scoped document, so they survive restarts with the transcripts in the same SQLite file.
//
// A session's public id is a UUID key, not the conversation id: conversation ids are small per-store integers,
// and the change log in jobs.db outlives any one store. The UI and FastAPI only ever see keys.
import { randomUUID } from "node:crypto";
import type { Context } from "@earendil-works/chord";
import { defineDoc, type Conversation, type ConversationId, type Harness } from "@earendil-works/pi-durable";
import { titleFrom, type SessionInfo, type SessionsState } from "@jobdash/agent-protocol";

type Stored = { active: string | null; items: (SessionInfo & { conversation: number })[] };

export const SessionsDoc = defineDoc<Stored & Record<string, never>>({
  kind: "jobdash.sessions",
  version: 1,
  scope: "session",
  initial: () => ({ active: null, items: [] }) as never,
});

type Reader = Pick<Harness, "snapshot">;

export async function sessionsState(harness: Reader, ctx: Context): Promise<SessionsState> {
  const s = await harness.snapshot(SessionsDoc, ctx);
  return {
    active: s?.active ?? null,
    items: [...(s?.items ?? [])].reverse().map(({ id, title, createdAt }) => ({ id, title, createdAt })),
  };
}

/** The session key of a conversation (tools know only their conversation id). */
export async function keyOf(reader: Reader, conversation: ConversationId, ctx: Context): Promise<string> {
  const s = await reader.snapshot(SessionsDoc, ctx);
  return s?.items.find((i) => i.conversation === Number(conversation))?.id ?? `conversation-${conversation}`;
}

export async function conversationOf(harness: Harness, key: string, ctx: Context): Promise<Conversation | undefined> {
  const s = await harness.snapshot(SessionsDoc, ctx);
  const item = s?.items.find((i) => i.id === key);
  return item ? harness.conversation(item.conversation as ConversationId, ctx) : undefined;
}

export async function createSession(harness: Harness, model: { provider: string; modelId: string }, ctx: Context): Promise<string> {
  const conv = await harness.createConversation({ ownership: { kind: "ownerless" }, agent: { model } }, ctx);
  const key = randomUUID();
  await harness.commit(async (tx) => {
    const doc = await tx.doc(SessionsDoc);
    doc.items.push({ id: key, conversation: Number(conv.id), title: "New session", createdAt: Date.now() });
    doc.active = key;
  }, ctx);
  return key;
}

export async function activate(harness: Harness, key: string, ctx: Context): Promise<boolean> {
  return harness.commit(async (tx) => {
    const doc = await tx.doc(SessionsDoc);
    if (!doc.items.some((s) => s.id === key)) return false;
    doc.active = key;
    return true;
  }, ctx);
}

/** The first question names the session. */
export async function nameIfNew(harness: Harness, key: string, firstMessage: string, ctx: Context): Promise<void> {
  await harness.commit(async (tx) => {
    const doc = await tx.doc(SessionsDoc);
    const item = doc.items.find((s) => s.id === key);
    if (item && item.title === "New session") item.title = titleFrom(firstMessage);
  }, ctx);
}

/** The active session's key, starting one if there is none. */
export async function ensureActive(harness: Harness, model: { provider: string; modelId: string }, ctx: Context): Promise<string> {
  const { active } = await sessionsState(harness, ctx);
  return active ?? createSession(harness, model, ctx);
}
