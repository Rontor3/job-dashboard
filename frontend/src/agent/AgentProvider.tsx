// One connection to the active session, shared by the Agent tab and every popover (a popover is a view into the
// active session, not a thread of its own). Also holds the cursor mode and the open popover.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import type { ElementContext, SessionsState } from "@jobdash/agent-protocol";
import { captureContext, captureTarget } from "./capture.ts";
import { activateSession, fetchSessions, newSession, sendMessage, stopSession, withdraw } from "./client.ts";
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
  ask(content: string, context?: ElementContext, whenBusy?: "steer" | "followUp"): Promise<number | undefined>;
  /** Alt+Up: withdraw the queued messages and return their text for the editor. */
  takeBack(): Promise<string[]>;
  /** Re-read the session list (after /name, /fork, /clone). */
  refreshSessions(): Promise<void>;
  stop(): Promise<void>;
  newSession(): Promise<void>;
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

export function AgentProvider({ children, tab, onOpenTab }: { children: ReactNode; tab?: string; onOpenTab?: () => void }) {
  const [sessions, setSessions] = useState<SessionsState>({ active: null, items: [] });
  const [thread, dispatch] = useReducer((s: ThreadState, a: Action) => (a.type === "reset" ? EMPTY : reduce(s, a.event)), EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(false);
  const [popover, setPopover] = useState<PopoverState | null>(null);
  const [focusEntry, setFocusEntry] = useState<number | null>(null);
  const active = sessions.active;
  const activeRef = useRef(active);
  activeRef.current = active;
  const threadRef = useRef(thread);
  threadRef.current = thread;

  useEffect(() => {
    fetchSessions().then(setSessions).catch((e) => setError(`The agent isn't reachable (${e.message}).`));
  }, []);

  useEffect(() => {
    dispatch({ type: "reset" });
    if (!active || typeof EventSource === "undefined") return undefined;
    const es = new EventSource(`/agent/sessions/${active}/events`);
    es.addEventListener("agent", (m) => {
      try {
        dispatch({ type: "event", event: JSON.parse((m as MessageEvent).data) });
      } catch {
        // a malformed frame: skip it
      }
    });
    es.onerror = () => setError(null);            // EventSource reconnects by itself; the next snapshot catches up
    return () => es.close();
  }, [active]);

  const sent = useRef(new Map<number, string>());       // submission id -> what was typed, for Alt+Up

  const ask = useCallback(async (content: string, context?: ElementContext, whenBusy?: "steer" | "followUp") => {
    setError(null);
    let id = activeRef.current;
    if (!id) {
      const s = await newSession();
      setSessions(s);
      id = s.id;
    }
    try {
      const { submission } = await sendMessage(id, content, context, whenBusy ?? (context ? "followUp" : "steer"));
      sent.current.set(Number(submission), content);
      fetchSessions().then(setSessions).catch(() => {});       // the first question names the session
      return Number(submission);
    } catch (e) {
      setError(`Couldn't send that: ${(e as Error).message}`);
      return undefined;
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
    if (question) void ask(question, context);
  }, [tab, ask]);

  const api = useMemo<AgentApi>(() => ({
    sessions, thread, error, ask, takeBack, cursor, setCursor, popover, openPopover, focusEntry,
    refreshSessions: async () => setSessions(await fetchSessions()),
    stop: async () => {
      if (activeRef.current) await stopSession(activeRef.current);
    },
    newSession: async () => setSessions(await newSession()),
    openSession: async (id) => setSessions(await activateSession(id)),
    closePopover: () => setPopover(null),
    openTab: (entryId) => {
      setFocusEntry(entryId ?? null);
      setPopover(null);
      onOpenTab?.();
    },
  }), [sessions, thread, error, ask, takeBack, cursor, popover, openPopover, focusEntry, onOpenTab]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}
