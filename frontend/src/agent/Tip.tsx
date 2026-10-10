// A hover / focus card with the whole story of an item (an agent's job and reach, a session's full title), drawn in
// a portal with fixed position so the scrolling rail can't clip it.
import { cloneElement, useRef, useState, type ReactElement, type ReactNode } from "react";
import { createPortal } from "react-dom";

const DELAY_MS = 250;

export default function Tip({ content, children }: { content: ReactNode; children: ReactElement<any> }) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const show = (el: HTMLElement) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const r = el.getBoundingClientRect();
      const side = r.right + 10 + 336 <= window.innerWidth;       // beside it when there's room, else just below
      setAt(side ? { top: Math.max(8, Math.min(r.top, window.innerHeight - 220)), left: r.right + 10 }
        : { top: Math.min(r.bottom + 6, window.innerHeight - 220), left: Math.max(8, Math.min(r.left, window.innerWidth - 336)) });
    }, DELAY_MS);
  };
  const hide = () => { clearTimeout(timer.current); setAt(null); };
  const child = cloneElement(children, {
    onMouseEnter: (e: React.MouseEvent<HTMLElement>) => show(e.currentTarget),
    onMouseLeave: hide,
    onFocus: (e: React.FocusEvent<HTMLElement>) => show(e.currentTarget),
    onBlur: hide,
  });
  return (
    <>
      {child}
      {at && createPortal(<div className="tip" role="tooltip" style={{ top: at.top, left: at.left }}>{content}</div>, document.body)}
    </>
  );
}
