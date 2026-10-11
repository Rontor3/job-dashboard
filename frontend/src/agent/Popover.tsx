// The popover: quick questions about one element, in place. They go to a side branch of the active session (one per
// element), so the conversation in the Agent tab isn't interrupted; the header opens that branch in the Agent tab.
import { useEffect, useRef } from "react";
import { ACTIONABLE_KINDS, anchorKind, type ElementContext } from "@jobdash/agent-protocol";
import { useAgent } from "./AgentProvider.tsx";
import { busyWith, exchangesFor, userTurn } from "./state.ts";
import { Composer, Thread } from "./Thread.tsx";

const WIDTH = 440;
const HEIGHT = 560;
const SIZE_KEY = "agent-popover-size";

/** The size the user last dragged the popover to (its corner is a resize handle), if any. */
function savedSize(): { w?: number; h?: number } {
  try { return JSON.parse(localStorage.getItem(SIZE_KEY) || "{}") as { w?: number; h?: number }; } catch { return {}; }
}

export default function Popover() {
  const agent = useAgent();
  const { popover } = agent;
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    let first = true;                                    // the observer reports the opening size too: not a drag
    const seen = new ResizeObserver(() => {
      if (first) { first = false; return; }
      try { localStorage.setItem(SIZE_KEY, JSON.stringify({ w: el.offsetWidth, h: el.offsetHeight })); } catch { /* private mode */ }
    });
    seen.observe(el);
    return () => seen.disconnect();
  }, [popover]);
  const thread = agent.aside.thread;
  useEffect(() => {
    if (!popover) return undefined;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") agent.closePopover(); };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [popover, agent]);
  if (!popover) return null;

  const { context, rect } = popover;
  // Without an anchor the exchange is matched by the element's text.
  const key = context.anchor ?? "";
  const fromHere = (c?: ElementContext) => (key ? c?.anchor === key : c?.text === context.text);
  const shown = key ? exchangesFor(thread.entries, key) : thread.entries.filter((e) => fromHere(userTurn(e)?.context));
  const busy = busyWith(thread);
  const mine = !!busy && fromHere(busy.context);            // the agent is on this element's question right now
  const waiting = thread.running && !mine && thread.inbox.length > 0;
  const canChange = !!context.anchor && (ACTIONABLE_KINDS as readonly string[]).includes(anchorKind(context.anchor));
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const want = savedSize();
  const width = Math.max(320, Math.min(want.w ?? WIDTH, vw - 16));
  const left = Math.max(8, Math.min(rect.left, vw - width - 8));
  // On whichever side of the element has more room (below when it fits), sized to that room, never over it; a size
  // the user dragged to wins, within the window.
  const below = vh - rect.bottom - 16;
  const above = rect.top - 16;
  const under = below >= Math.min(HEIGHT, 300) || below >= above;
  const height = want.h ? Math.max(240, Math.min(want.h, vh - 16)) : Math.max(260, Math.min(HEIGHT, under ? below : above));
  const top = under ? Math.max(8, Math.min(rect.bottom + 8, vh - height - 8)) : Math.max(8, rect.top - 8 - height);

  return (
    <div ref={box} className="agent-popover" data-agent-ui role="dialog" aria-label="Ask the agent" style={{ left, top, width, height }}>
      <div className="agent-popover-head">
        <button className="linkish" title="Open in the Agent tab"
          onClick={() => { if (agent.aside.id) void agent.openSession(agent.aside.id).then(() => agent.openTab(shown[0]?.id)); else agent.openTab(); }}>
          {context.label || context.heading || context.anchor || "This part of the page"}
        </button>
        <button className="btn btn-quiet btn-sm" aria-label="Close" onClick={agent.closePopover}>×</button>
      </div>
      {!canChange && <p className="agent-widget-why">The agent can explain this, but can't change it from here.</p>}
      <Thread entries={shown} partial={mine ? thread.partial : null} running={mine && thread.running}
        toolsRunning={thread.toolsRunning} />
      {waiting && <p className="agent-busy">Agent is busy with “{busy?.question}”; your question is next.</p>}
      <Composer placeholder="Ask about this…" autoFocus onSend={(t) => void agent.askAside(t, context)} />
    </div>
  );
}
