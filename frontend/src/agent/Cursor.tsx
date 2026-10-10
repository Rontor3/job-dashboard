// The cursor: a header button turns it on; hovering outlines what a click would capture; a click opens the popover
// there; Esc cancels. No default keyboard shortcut (spec Q14). It ignores the agent's own UI (`data-agent-ui`).
import { useEffect, useState } from "react";
import { useAgent } from "./AgentProvider.tsx";
import { captureTarget } from "./capture.ts";

type Box = { top: number; left: number; width: number; height: number };

const ours = (el: Element | null) => !el || !!el.closest("[data-agent-ui]");

export function CursorButton() {
  const { cursor, setCursor } = useAgent();
  return (
    <button className="btn btn-sm agent-cursor-btn" data-agent-ui aria-pressed={cursor}
      title="Point at anything to ask the agent about it (Esc to cancel)" onClick={() => setCursor(!cursor)}>
      {cursor ? "Pick something…" : "Ask about…"}
    </button>
  );
}

export function CursorOverlay() {
  const { cursor, setCursor, openPopover } = useAgent();
  const [box, setBox] = useState<Box | null>(null);

  useEffect(() => {
    if (!cursor) {
      setBox(null);
      return undefined;
    }
    const move = (e: MouseEvent) => {
      const el = e.target as Element;
      if (ours(el)) return setBox(null);
      const r = captureTarget(el).getBoundingClientRect();
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    const click = (e: MouseEvent) => {
      const el = e.target as Element;
      if (ours(el)) return;
      e.preventDefault();
      e.stopPropagation();
      openPopover(el);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setCursor(false); };
    document.addEventListener("mousemove", move, true);
    document.addEventListener("click", click, true);
    document.addEventListener("keydown", key, true);
    document.body.classList.add("agent-cursor-on");
    return () => {
      document.removeEventListener("mousemove", move, true);
      document.removeEventListener("click", click, true);
      document.removeEventListener("keydown", key, true);
      document.body.classList.remove("agent-cursor-on");
    };
  }, [cursor, setCursor, openPopover]);

  return box ? <div className="agent-outline" data-agent-ui style={box} aria-hidden /> : null;
}
