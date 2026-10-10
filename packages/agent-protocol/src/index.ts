// What the agent service (agent/) and the dashboard (frontend/) agree on: session state, the element context a
// cursor click attaches to a question, the tools that ask the human for something, and change-log summaries.

/** A component's semantic anchor, `<kind>:<id>`, from its `data-agent` attribute: `job:1234`, `qbank:cgpa`. */
export type Anchor = string;

/** What a cursor click captured. No screenshots: the model reads text only. */
export interface ElementContext {
  anchor?: Anchor;
  text: string;
  label?: string;
  heading?: string;
  tab?: string;
}

export interface SessionInfo {
  id: string;
  title: string;
  createdAt: number;
  /** The session this one was forked or cloned from. */
  parent?: string;
  /** The parent's last entry this one still shares: where it branches off in /tree. */
  forkAt?: number;
  /** A side branch opened from another page (a popover, the Inbox): it never becomes the active session by itself. */
  aside?: boolean;
  /** A model chosen with /model for this session only; otherwise it follows the app's LLM_MODEL. */
  model?: string;
  /** The agent profile it runs as (scout, critic, advocate, or the user's own); none = the plain playbook. */
  profile?: string;
}

/** An agent profile: a system prompt and a tool set for one kind of work (agent/src/team.ts). */
export interface ProfileInfo {
  name: string;
  description: string;
  source: "base" | "user";
  /** What it may do: read only, change your data (with Undo), or also propose applying (you confirm). */
  power?: "read" | "write" | "act";
  /** Its tools, when the profile limits them (none = every tool). */
  tools?: string[];
}

/** One Inbox update (job_dashboard/notifications.py). */
export interface NotificationItem {
  id: number;
  at: string;
  kind: "submitted" | "parked" | "failed" | "matches" | "tracker" | "agent";
  level: "info" | "success" | "action" | "warning";
  title: string;
  body: string | null;
  job_id: number | null;
  data: { job_ids?: number[]; reason?: string };
  source: string;
  read_at: string | null;
}

/** A slash command as the editor's menu shows it. Prompt templates (data/agent/prompts/*.md) are commands too. */
export interface CommandInfo {
  name: string;
  description: string;
  args?: string;
  kind: "builtin" | "template";
}

/** `/session`: what pi shows for the current session. */
export interface SessionStats {
  id: string;
  title: string;
  createdAt: number;
  parent?: string;
  conversation: number;
  model: string;
  thinkingLevel: string;
  contextWindow: number;
  contextTokens: number;
  entries: number;
  messages: { user: number; assistant: number; toolCalls: number; toolResults: number };
  usage: { input: number; output: number; cacheRead: number; cacheWrite: number; total: number; cost: number };
  tools: string[];
  prompt: { file: string; loaded: boolean }[];
}

export interface SessionsState {
  active: string | null;
  items: SessionInfo[];
}

/** One change-log row as the api reports it in `X-Changes` (job_dashboard/changes.py). */
export interface ChangeSummary {
  id: number;
  entity: string;
  entity_id: string | null;
  field: string | null;
  before: unknown;
  after: unknown;
  undoable: boolean;
}

/** Tools that stop the run and put a widget in the thread for the human. */
export const WIDGET_TOOLS = {
  secret: "request_secret",
  upload: "request_resume_upload",
  confirm: "propose_action",
} as const;

/** Keys the secure-input widget may write to .env (mirrors api/setup_routes.SECRET_KEYS). */
export const SECRET_KEYS = [
  "LLM_API_KEY", "TINYFISH_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
  "CAREER_AGENT_EMAIL", "CAREER_AGENT_FIRST_NAME", "CAREER_AGENT_LAST_NAME",
] as const;
export type SecretKey = (typeof SECRET_KEYS)[number];

const OPEN = "<element";
const CLOSE = "</element>";

const attr = (v: string) => v.replace(/[&"<>]/g, (c) => ({ "&": "&amp;", '"': "&quot;", "<": "&lt;", ">": "&gt;" })[c]!);
const unattr = (v: string) => v.replace(/&(amp|quot|lt|gt);/g, (_, e: string) => ({ amp: "&", quot: '"', lt: "<", gt: ">" })[e]!);
const body = (v: string) => v.replaceAll(CLOSE, "</ element>").trim();

/**
 * The user message for a question asked about an element: the element's context first, then the question. The
 * anchor travels inside the message itself, so the transcript alone tells which popover a message belongs to.
 */
export function encodeElementMessage(context: ElementContext | undefined, question: string): string {
  if (!context) return question;
  const attrs = [context.anchor && `anchor="${attr(context.anchor)}"`, context.tab && `tab="${attr(context.tab)}"`]
    .filter(Boolean).join(" ");
  const lines = [
    context.heading && `heading: ${body(context.heading)}`,
    context.label && `label: ${body(context.label)}`,
    `text: ${body(context.text).slice(0, 2000)}`,
  ].filter(Boolean);
  return `${OPEN}${attrs ? " " + attrs : ""}>\n${lines.join("\n")}\n${CLOSE}\n\n${question}`;
}

export function parseElementMessage(text: string): { context?: ElementContext; question: string } {
  if (!text.startsWith(OPEN)) return { question: text };
  const end = text.indexOf(CLOSE);
  const headEnd = text.indexOf(">");
  if (end < 0 || headEnd < 0 || headEnd > end) return { question: text };
  const head = text.slice(OPEN.length, headEnd);
  const get = (name: string) => {
    const m = new RegExp(`${name}="([^"]*)"`).exec(head);
    return m ? unattr(m[1]!) : undefined;
  };
  const context: ElementContext = { text: "" };
  for (const line of text.slice(headEnd + 1, end).split("\n")) {
    const m = /^(heading|label|text): (.*)$/.exec(line);
    if (m) context[m[1] as "heading" | "label" | "text"] = m[2]!;
  }
  const anchor = get("anchor");
  const tab = get("tab");
  if (anchor) context.anchor = anchor;
  if (tab) context.tab = tab;
  return { context, question: text.slice(end + CLOSE.length).trim() };
}

/** `job:12` → `job`. */
export const anchorKind = (anchor: Anchor) => anchor.split(":", 1)[0]!;

/** Kinds of element the agent has tools for; on anything else it explains but can't change. */
export const ACTIONABLE_KINDS = ["job", "qbank", "profile", "answer", "question", "setting", "setup", "notification", "about"] as const;

/** A short session title from the first question. */
export function titleFrom(text: string): string {
  const q = parseElementMessage(text).question.replace(/\s+/g, " ").trim();
  return q.length > 60 ? q.slice(0, 57) + "…" : q || "New session";
}
