// What a command opens above the editor, as pi's selectors and panels: a filterable picker (models, sessions,
// fork points), the session tree, /session stats, /hotkeys, /settings. Up/Down choose, Enter picks, Esc closes.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { SessionInfo, SessionStats } from "@jobdash/agent-protocol";

export interface PickItem { id: string; label: string; hint?: string; current?: boolean }

export function Picker({ title, items, onPick, onClose, empty }: {
  title: string; items: PickItem[]; onPick(item: PickItem): void; onClose(): void; empty?: string;
}) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { input.current?.focus(); }, []);
  const shown = useMemo(() => items.filter((i) => `${i.label} ${i.hint ?? ""}`.toLowerCase().includes(q.toLowerCase())), [items, q]);
  return (
    <div className="pi-overlay" role="dialog" aria-label={title}>
      <div className="pi-overlay-title">{title}</div>
      <input ref={input} aria-label={`Filter ${title}`} value={q} placeholder="type to filter"
        onChange={(e) => { setQ(e.target.value); setSel(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setSel(Math.min(sel + 1, shown.length - 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setSel(Math.max(sel - 1, 0)); }
          if (e.key === "Enter" && shown[sel]) { e.preventDefault(); onPick(shown[sel]!); }
          if (e.key === "Escape") { e.preventDefault(); onClose(); }
        }} />
      <ul className="pi-pick" role="listbox">
        {shown.map((i, n) => (
          <li key={i.id} role="option" aria-selected={n === sel} onMouseEnter={() => setSel(n)} onClick={() => onPick(i)}>
            <span>{i.current ? "● " : "  "}{i.label}</span>{i.hint && <span className="pi-pick-hint">{i.hint}</span>}
          </li>
        ))}
        {!shown.length && <li className="pi-pick-empty">{empty ?? "Nothing matches"}</li>}
      </ul>
    </div>
  );
}

export function Panel({ title, onClose, children }: { title: string; onClose(): void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.focus(); }, []);
  return (
    <div className="pi-overlay" role="dialog" aria-label={title} tabIndex={-1} ref={box}
      onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } }}>
      <div className="pi-overlay-title">{title}<button className="pi-close" aria-label="Close" onClick={onClose}>esc</button></div>
      <div className="pi-panel">{children}</div>
    </div>
  );
}

const n = (x: number) => (x >= 1000 ? `${(x / 1000).toFixed(x >= 10_000 ? 0 : 1)}k` : String(x));

export function StatsPanel({ s, onClose }: { s: SessionStats; onClose(): void }) {
  const rows: [string, ReactNode][] = [
    ["Session", `${s.title}  (${s.id})`],
    ["Created", new Date(s.createdAt).toLocaleString()],
    ...(s.parent ? [["Forked from", s.parent] as [string, ReactNode]] : []),
    ["Model", `${s.model} · thinking ${s.thinkingLevel}`],
    ["Context", `${n(s.contextTokens)} of ${n(s.contextWindow)} tokens (${s.contextWindow ? ((100 * s.contextTokens) / s.contextWindow).toFixed(1) : "?"}%)`],
    ["Messages", `${s.messages.user} user · ${s.messages.assistant} assistant · ${s.messages.toolCalls} tool calls · ${s.entries} entries`],
    ["Tokens", `↑${n(s.usage.input)} ↓${n(s.usage.output)} R${n(s.usage.cacheRead)} W${n(s.usage.cacheWrite)} · total ${n(s.usage.total)}`],
    ["Cost", `$${s.usage.cost.toFixed(4)}`],
    ["Tools", s.tools.join(", ")],
    ["Prompt", s.prompt.map((p) => `${p.file.replace(/^.*\/(docs|data)\//, "$1/")}${p.loaded ? "" : " (missing)"}`).join(" · ")],
  ];
  return (
    <Panel title="/session" onClose={onClose}>
      <table className="pi-kv"><tbody>{rows.map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}</tbody></table>
    </Panel>
  );
}

export const HOTKEYS: [string, string][] = [
  ["Enter", "Send; while the agent works, steer the current task"],
  ["Alt+Enter", "Queue a follow-up for after the current task"],
  ["Shift+Enter", "New line"],
  ["Esc", "Stop the agent (queued messages return to the editor)"],
  ["Alt+Up", "Take queued messages back into the editor"],
  ["Up / Down", "Prompt history"],
  ["/", "Commands (Tab completes, Enter runs)"],
  ["Shift+Tab", "Cycle the thinking level"],
  ["Ctrl+L", "Pick a model"],
  ["Ctrl+O", "Expand or collapse tool output"],
  ["Ctrl+T", "Show or hide thinking"],
  ["Ctrl+C", "Clear the editor"],
];

export function HotkeysPanel({ onClose }: { onClose(): void }) {
  return (
    <Panel title="/hotkeys" onClose={onClose}>
      <table className="pi-kv"><tbody>{HOTKEYS.map(([k, v]) => <tr key={k}><th><kbd>{k}</kbd></th><td>{v}</td></tr>)}</tbody></table>
    </Panel>
  );
}

/** The session tree: forks and clones under the session they came from. */
export function treeItems(items: SessionInfo[], active: string | null): PickItem[] {
  const kids = new Map<string | undefined, SessionInfo[]>();
  const ids = new Set(items.map((i) => i.id));
  for (const s of items) {
    const p = s.parent && ids.has(s.parent) ? s.parent : undefined;
    kids.set(p, [...(kids.get(p) ?? []), s]);
  }
  const out: PickItem[] = [];
  const walk = (parent: string | undefined, depth: number) => {
    for (const s of [...(kids.get(parent) ?? [])].sort((a, b) => a.createdAt - b.createdAt)) {
      out.push({ id: s.id, label: `${"  ".repeat(depth)}${depth ? "└ " : ""}${s.title}`, hint: new Date(s.createdAt).toLocaleString(), current: s.id === active });
      walk(s.id, depth + 1);
    }
  };
  walk(undefined, 0);
  return out;
}
