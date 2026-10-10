// The popover: quick questions about one element, in place. It is a view into the active session showing only the
// exchanges started from this element; its header opens the Agent tab at that point. If the agent is busy, the
// question waits its turn and the popover says so.
import { useEffect } from "react";
import { ACTIONABLE_KINDS, anchorKind } from "@jobdash/agent-protocol";
import { useAgent } from "./AgentProvider.tsx";
import { busyWith, exchangesFor, userTurn } from "./state.ts";
import { Composer, Thread } from "./Thread.tsx";

const WIDTH = 380;
const HEIGHT = 420;

export default function Popover() {
  const agent = useAgent();
  const { popover, thread } = agent;
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
  const shown = key ? exchangesFor(thread.entries, key)
    : thread.entries.filter((e) => userTurn(e)?.context?.text === context.text);
  const lastMine = shown.map(userTurn).filter(Boolean).at(-1)?.question;
  const busy = busyWith(thread);
  const mine = !!busy && busy === lastMine;                 // the agent is on this element's question right now
  const waiting = thread.running && !mine && thread.inbox.length > 0;
  const canChange = !!context.anchor && (ACTIONABLE_KINDS as readonly string[]).includes(anchorKind(context.anchor));
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const left = Math.max(8, Math.min(rect.left, vw - WIDTH - 8));
  // Below the element when there's room, else above it, always on screen.
  const top = Math.max(8, rect.bottom + 8 + HEIGHT <= vh ? rect.bottom + 8 : Math.min(rect.top - 8 - HEIGHT, vh - HEIGHT - 8));

  return (
    <div className="agent-popover" data-agent-ui role="dialog" aria-label="Ask the agent" style={{ left, top, width: WIDTH, maxHeight: HEIGHT }}>
      <div className="agent-popover-head">
        <button className="linkish" title="Open in the Agent tab"
          onClick={() => agent.openTab(shown[0]?.id)}>
          {context.heading || context.label || context.anchor || "This part of the page"}
        </button>
        <button className="btn btn-quiet btn-sm" aria-label="Close" onClick={agent.closePopover}>×</button>
      </div>
      {!canChange && <p className="agent-widget-why">The agent can explain this, but can't change it from here.</p>}
      <Thread entries={shown} partial={mine ? thread.partial : null} running={mine && thread.running}
        toolsRunning={thread.toolsRunning} />
      {waiting && <p className="agent-busy">Agent is busy with “{busy}”; your question is next.</p>}
      <Composer placeholder="Ask about this…" autoFocus onSend={(t) => void agent.ask(t, context)} />
    </div>
  );
}
