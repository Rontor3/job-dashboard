import React, { useEffect, useRef } from "react";

// "Where should this apply?" as a choice card (like Claude's question pop-up): each option says what it means and how
// many past questions it would have changed; the agent's suggestion is marked; 1–4 or the arrows pick one.

export const SCOPE_OPTIONS = [
  { key: "question", label: "Only this question", text: "Just this exact wording, wherever a form asks it." },
  { key: "similar", label: "Questions about the same thing", text: "Any question that asks the same kind of thing, in other words." },
  { key: "long", label: "Every essay answer", text: "All long free-text answers, whatever they ask." },
  { key: "short", label: "Every short field", text: "All short answers: boxes, choices, dates, numbers." },
];

export default function ScopeChoice({ value, suggested, reaches = {}, onChange }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const onKey = (e) => {
      const i = SCOPE_OPTIONS.findIndex((o) => o.key === value);
      if (/^[1-4]$/.test(e.key)) onChange(SCOPE_OPTIONS[Number(e.key) - 1].key);
      else if (e.key === "ArrowDown" || e.key === "ArrowRight") onChange(SCOPE_OPTIONS[(i + 1) % 4].key);
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") onChange(SCOPE_OPTIONS[(i + 3) % 4].key);
      else return;
      e.preventDefault();
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [value, onChange]);

  const picked = reaches[value];
  return (
    <div className="scope-choice" ref={ref} role="radiogroup" aria-label="Applies to" tabIndex={-1}>
      <div className="scope-q">Where should this apply?</div>
      {SCOPE_OPTIONS.map((o, i) => {
        const r = reaches[o.key];
        return (
          <button key={o.key} type="button" role="radio" aria-checked={value === o.key} className="scope-opt"
                  onClick={() => onChange(o.key)}>
            <span className="scope-num" aria-hidden="true">{i + 1}</span>
            <span className="scope-body">
              <span className="scope-label">
                {o.label}{o.key === suggested && <span className="scope-tag">suggested</span>}
              </span>
              <span className="scope-text">{o.text}</span>
            </span>
            <span className="scope-reach" title="Past questions this would have changed">
              {r ? `${r.count} past` : "…"}
            </span>
          </button>
        );
      })}
      {picked && picked.count > 0 && (
        <details className="scope-examples">
          <summary>See the {picked.count} past question{picked.count === 1 ? "" : "s"}</summary>
          <ul>{picked.examples.map((x) => <li key={x.label}>{x.label.replace(/\s+/g, " ").trim()}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
