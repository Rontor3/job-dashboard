// A session's thread as the dashboard sees it, built from the agent service's event stream: a snapshot, then events
// that apply on top of it (Pi Durable's agent events). Pure, so it's tested without a server.
import { parseElementMessage, type ChangeSummary, type ElementContext } from "@jobdash/agent-protocol";

export type TextBlock = { type: "text"; text: string };
export type ThinkingBlock = { type: "thinking"; thinking: string };
export type ToolCallBlock = { type: "toolCall"; id: string; name: string; arguments: Record<string, unknown> };
export type Block = TextBlock | ThinkingBlock | ToolCallBlock;

export interface Message {
  role: "user" | "assistant" | "toolResult";
  content: string | Block[];
  toolCallId?: string;
  toolName?: string;
  isError?: boolean;
  details?: { changes?: ChangeSummary[]; widget?: string; [k: string]: unknown };
}

export interface Entry {
  id: number;
  kind: string;
  model?: Message[];
}

export interface ThreadState {
  entries: Entry[];
  partial: Message | null;           // the assistant message streaming in
  running: boolean;
  inbox: number[];                   // queued submissions (questions waiting their turn)
  toolsRunning: string[];            // tool names in flight
  failure?: string;
}

export const EMPTY: ThreadState = { entries: [], partial: null, running: false, inbox: [], toolsRunning: [] };

type Change =
  | { type: "text_start" | "thinking_start" | "toolcall_start"; contentIndex: number; block: Block }
  | { type: "text_delta" | "thinking_delta"; contentIndex: number; delta: string }
  | { type: "toolcall_delta"; contentIndex: number; delta: string }
  | { type: "block"; contentIndex: number; block: Block }
  | { type: "message"; message: Message };

// The service forwards Pi Durable's events as they are; only the fields used here are typed.
export type AgentEvent =
  | { type: "snapshot"; entries: Entry[]; run?: unknown; generation?: { message?: Message }; inbox?: { id: number }[]; tools?: { name?: string }[] }
  | { type: "run_start" | "run_end" }
  | { type: "message_start"; message: Message }
  | { type: "message_update"; changes: Change[] }
  | { type: "message_end" | "entry_appended"; entry: Entry }
  | { type: "tool_execution_start"; toolCallId: string; toolName: string }
  | { type: "tool_execution_end"; toolCallId: string; toolName: string; entry?: Entry }
  | { type: "inbox_update"; items: { id: number }[] }
  | { type: "task_failed"; message: string }
  | { type: string; [k: string]: unknown };

function withEntry(entries: Entry[], entry: Entry | undefined): Entry[] {
  if (!entry || entries.some((e) => e.id === entry.id)) return entries;
  return [...entries, entry].sort((a, b) => a.id - b.id);
}

function applyChange(msg: Message, c: Change): Message {
  if (c.type === "message") return c.message;
  const content = Array.isArray(msg.content) ? [...msg.content] : [];
  const at = content[c.contentIndex];
  if (c.type === "text_start" || c.type === "thinking_start" || c.type === "toolcall_start" || c.type === "block") {
    content[c.contentIndex] = c.block;
  } else if (c.type === "text_delta" && at?.type === "text") {
    content[c.contentIndex] = { ...at, text: at.text + c.delta };
  } else if (c.type === "thinking_delta" && at?.type === "thinking") {
    content[c.contentIndex] = { ...at, thinking: at.thinking + c.delta };
  }
  return { ...msg, content };
}

export function reduce(state: ThreadState, event: AgentEvent): ThreadState {
  switch (event.type) {
    case "snapshot": {
      const e = event as Extract<AgentEvent, { type: "snapshot" }>;
      return {
        entries: [...e.entries].sort((a, b) => a.id - b.id),
        partial: e.generation?.message ?? null,
        running: !!e.run,
        inbox: (e.inbox ?? []).map((i) => i.id),
        toolsRunning: (e.tools ?? []).map((t) => t.name ?? "tool"),
      };
    }
    case "run_start":
      return { ...state, running: true, failure: undefined };
    case "run_end":
      return { ...state, running: false, partial: null, toolsRunning: [] };
    case "message_start": {
      const m = (event as { message: Message }).message;
      return m.role === "assistant" ? { ...state, partial: m } : state;
    }
    case "message_update":
      return state.partial
        ? { ...state, partial: (event as { changes: Change[] }).changes.reduce(applyChange, state.partial) }
        : state;
    case "message_end":
    case "entry_appended": {
      const entry = (event as { entry: Entry }).entry;
      const done = entry.kind === "pi.assistant";
      return { ...state, entries: withEntry(state.entries, entry), partial: done ? null : state.partial };
    }
    case "tool_execution_start":
      return { ...state, toolsRunning: [...state.toolsRunning, (event as { toolName: string }).toolName] };
    case "tool_execution_end": {
      const e = event as { toolName: string; entry?: Entry };
      const i = state.toolsRunning.indexOf(e.toolName);
      return {
        ...state,
        entries: withEntry(state.entries, e.entry),
        toolsRunning: i < 0 ? state.toolsRunning : state.toolsRunning.filter((_, j) => j !== i),
      };
    }
    case "inbox_update":
      return { ...state, inbox: (event as { items: { id: number }[] }).items.map((i) => i.id) };
    case "task_failed":
      return { ...state, failure: String((event as { message: unknown }).message) };
    default:
      return state;
  }
}

/** The text of a message, whichever shape its content has. */
export function textOf(msg: Message | undefined): string {
  if (!msg) return "";
  if (typeof msg.content === "string") return msg.content;
  return msg.content.filter((b): b is TextBlock => b.type === "text").map((b) => b.text).join("");
}

export interface UserTurn {
  entry: Entry;
  question: string;
  context?: ElementContext;
}

export function userTurn(entry: Entry): UserTurn | undefined {
  if (entry.kind !== "pi.user") return undefined;
  const { context, question } = parseElementMessage(textOf(entry.model?.[0]));
  return { entry, question, context };
}

/**
 * A popover shows only the exchanges started from its element: each user message carrying that anchor, and what
 * followed it up to the next user message.
 */
export function exchangesFor(entries: Entry[], anchor: string): Entry[] {
  const out: Entry[] = [];
  let inside = false;
  for (const e of entries) {
    const turn = userTurn(e);
    if (turn) inside = turn.context?.anchor === anchor;
    if (inside) out.push(e);
  }
  return out;
}

/** What the agent is working on: the question that started the current run. */
export function busyWith(state: ThreadState): string | undefined {
  if (!state.running) return undefined;
  for (let i = state.entries.length - 1; i >= 0; i--) {
    const turn = userTurn(state.entries[i]!);
    if (turn) return turn.question;
  }
  return undefined;
}
