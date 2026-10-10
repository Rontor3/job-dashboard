// One connection to the active session (the Agent tab), and one to the side branch the popover and the Inbox talk
// to: a question asked from another page forks the conversation at its tip into a branch of its own, so the
// conversation you're having in the Agent tab carries on undisturbed. Also holds the cursor mode and the popover.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import type { ElementContext, SessionsState } from "@jobdash/agent-protocol";
import { captureContext, captureTarget } from "./capture.ts";
import { activateSession, fetchSessions, newSession, runCommand, sendMessage, stopSession, withdraw, type Picture } from "./client.ts";
import { EMPTY, reduce, type AgentEvent, type ThreadState } from "./state.ts";

export interface PopoverState {
  context: ElementContext;
  rect: { top: number; left: number; bottom: number; right: number };
}

export interface AgentApi {
  sessions: SessionsState;
  thread: ThreadState;
  error: string | null;
  /** Send a message; while the agent works, `whenBusy` steers it (default) or queues a follow-up. */
  ask(content: string, context?: ElementContext, whenBusy?: "steer" | "followUp", images?: Picture[]): Promise<number | undefined>;
  /** Ask in a side branch of the active session (one per element or topic), leaving the active session alone. */
  askAside(content: string, context?: ElementContext, title?: string): Promise<void>;
  /** The side branch the popover shows, and its transcript. */
  aside: { id: string | null; thread: ThreadState };
  /** Alt+Up: withdraw the queued messages and return their text for the editor. */
  takeBack(): Promise<string[]>;
  /** Re-read the session list (after /name, /fork, /clone). */
  refreshSessions(): Promise<void>;
  stop(): Promise<void>;
  newSession(profile?: string): Promise<void>;
  /** Hand the agent a task: a new session (as `profile` when given) with `message` sent, and the Agent tab shown. */
  start(message: string, opts?: { profile?: string; context?: ElementContext }): Promise<void>;
  openSession(id: string): Promise<void>;
  cursor: boolean;
  setCursor(on: boolean): void;
  popover: PopoverState | null;
  /** Open the popover on an element, optionally sending a question about it at once. */
  openPopover(el: Element, question?: string): void;
  closePopover(): void;
  /** Show the Agent tab, scrolled to an entry when given. */
  openTab(entryId?: number): void;
  focusEntry: number | null;
}

const Ctx = createContext<AgentApi | null>(null);

export function useAgent(): AgentApi {
  const api = useContext(Ctx);
  if (!api) throw new Error("useAgent outside AgentProvider");
  return api;
}

/** For components that also render without the agent (older tests). */
export const useOptionalAgent = () => useContext(Ctx);

type Action = { type: "event"; event: AgentEvent } | { type: "reset" };

// Which side branch each element or topic talks to, kept across reloads (a convenience: a lost map only means a
// fresh branch next time).
const ASIDES_KEY = "agent-asides";
function loadAsides(): Map<string, string> {
  try {
    return new Map(Object.entries(JSON.parse(localStorage.getItem(ASIDES_KEY) ?? "{}") as Record<string, string>));
  } catch {
    return new Map();
  }
}
function saveAsides(m: Map<string, string>) {
  try {
    localStorage.setItem(ASIDES_KEY, JSON.stringify(Object.fromEntries([...m].slice(-200))));
  } catch {
    // private mode: this page only
  }
}
const threadReducer = (s: ThreadState, a: Action) => (a.type === "reset" ? EMPTY : reduce(s, a.event));

/** Follow one session's events into a thread. */
function useSessionThread(id: string | null) {
  const [thread, dispatch] = useReducer(threadReducer, EMPTY);
  useEffect(() => {
    dispatch({ type: "reset" });
    if (!id || typeof EventSource === "undefined") return undefined;
    const es = new EventSource(`/agent/sessions/${id}/events`);
    es.addEventListener("agent", (m) => {
      try {
        dispatch({ type: "event", event: JSON.parse((m as MessageEvent).data) });
      } catch {
        // a malformed frame: skip it
      }
    });
    return () => es.close();
  }, [id]);
  return thread;
}

export function AgentProvider({ children, tab, onOpenTab }: { children: ReactNode; tab?: string; onOpenTab?: () => void }) {
  const [sessions, setSessions] = useState<SessionsState>({ active: null, items: [] });
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(false);
  const [popover, setPopover] = useState<PopoverState | null>(null);
  const [focusEntry, setFocusEntry] = useState<number | null>(null);
  const active = sessions.active;
  const thread = useSessionThread(active);
  const [asideId, setAsideId] = useState<string | null>(null);
  const asideThread = useSessionThread(asideId);
  const asides = useRef(loadAsides());                  // element or topic -> its side branch
  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;
  const activeRef = useRef(active);
  activeRef.current = active;
  const threadRef = useRef(thread);
  threadRef.current = thread;

  useEffect(() => {
    fetchSessions().then(setSessions).catch((e) => setError(`The agent isn't reachable (${e.message}).`));
  }, []);

  const sent = useRef(new Map<number, string>());       // submission id -> what was typed, for Alt+Up

  const ask = useCallback(async (content: string, context?: ElementContext, whenBusy?: "steer" | "followUp", images?: Picture[]) => {
    setError(null);
    let id = activeRef.current;
    if (!id) {
      const s = await newSession();
      setSessions(s);
      id = s.id;
    }
    try {
      const { submission } = await sendMessage(id, content, context, whenBusy ?? (context ? "followUp" : "steer"), images);
      sent.current.set(Number(submission), content);
      fetchSessions().then(setSessions).catch(() => {});       // the first question names the session
      return Number(submission);
    } catch (e) {
      setError(`Couldn't send that: ${(e as Error).message}`);
      return undefined;
    }
  }, []);

  const askAside = useCallback(async (content: string, context?: ElementContext, title?: string) => {
    setError(null);
    const topic = context?.anchor ?? context?.text?.slice(0, 80) ?? title ?? "aside";
    try {
      let id = asides.current.get(topic);
      const items = sessionsRef.current.items.length ? sessionsRef.current.items : (await fetchSessions()).items;
      if (id && !items.some((s) => s.id === id)) id = undefined;          // that branch is gone
      if (!id) {
        const from = activeRef.current;
        const name = title ?? `About: ${(context?.heading || context?.label || context?.text || "this").slice(0, 60)}`;
        id = from ? (await runCommand(from, "branch", "", { title: name })).session : (await newSession()).id;
        if (!id) throw new Error("no branch");
        asides.current.set(topic, id);
        saveAsides(asides.current);
      }
      setAsideId(id);
      await sendMessage(id, content, context, "followUp");
      fetchSessions().then(setSessions).catch(() => {});
    } catch (e) {
      setError(`Couldn't send that: ${(e as Error).message}`);
    }
  }, []);

  const takeBack = useCallback(async () => {
    const id = activeRef.current;
    if (!id) return [];
    const back: string[] = [];
    for (const item of threadRef.current.inbox) {
      try {
        if ((await withdraw(id, item.id)).result === "aborted") back.push(sent.current.get(item.id) ?? "");
      } catch {
        // already placed
      }
    }
    return back.filter(Boolean);
  }, []);

  const openPopover = useCallback((el: Element, question?: string) => {
    const context = captureContext(el, tab);
    const r = captureTarget(el).getBoundingClientRect();
    setPopover({ context, rect: { top: r.top, left: r.left, bottom: r.bottom, right: r.right } });
    setCursor(false);
    const known = asides.current.get(context.anchor ?? context.text?.slice(0, 80) ?? "");
    setAsideId(known ?? null);
    if (question) void askAside(question, context);
  }, [tab, askAside]);

  const api = useMemo<AgentApi>(() => ({
    sessions, thread, error, ask, askAside, aside: { id: asideId, thread: asideThread }, takeBack, cursor, setCursor,
    popover, openPopover, focusEntry,
    refreshSessions: async () => setSessions(await fetchSessions()),
    stop: async () => {
      if (activeRef.current) await stopSession(activeRef.current);
    },
    newSession: async (profile) => setSessions(await newSession(profile)),
    start: async (message, opts = {}) => {
      try {
        const s = await newSession(opts.profile);
        activeRef.current = s.id;
        setSessions(s);
        await ask(message, opts.context, "followUp");
      } catch (e) {
        setError(`Couldn't start that: ${(e as Error).message}`);
      }
      setPopover(null);
      onOpenTab?.();
    },
    openSession: async (id) => setSessions(await activateSession(id)),
    closePopover: () => setPopover(null),
    openTab: (entryId) => {
      setFocusEntry(entryId ?? null);
      setPopover(null);
      onOpenTab?.();
    },
  }), [sessions, thread, error, ask, askAside, asideId, asideThread, takeBack, cursor, popover, openPopover, focusEntry, onOpenTab]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}
