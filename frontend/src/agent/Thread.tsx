// A session's messages: the user's questions (with what they pointed at), the agent's answers (thinking folded
// away), a "Changed X → Y · Undo" chip for every change, and the widgets the agent asks for.
import { useEffect, useRef, useState } from "react";
import type { ChangeSummary } from "@jobdash/agent-protocol";
import { undoChange } from "./client.ts";
import { textOf, userTurn, type Block, type Entry, type Message } from "./state.ts";
import { ConfirmWidget, SecretWidget, UploadWidget } from "./Widgets.tsx";

const ENTITY: Record<string, string> = {
  profile: "Profile", qbank: "Saved answer", qa_row: "Application answer", setting: "Setting", config: "Setting",
  job: "Job", file: "File",
};

export function show(v: unknown): string {
  if (v == null || v === "") return "—";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 60 ? `${s.slice(0, 57)}…` : s;
}

function changeLabel(c: ChangeSummary): string {
  const what = c.entity === "qbank" && c.field === "status" ? "Saved question" : ENTITY[c.entity] ?? c.entity;
  const field = c.entity === "file" ? c.entity_id : c.entity === "setting" || c.entity === "config" ? c.entity_id
    : c.entity === "job" ? `#${c.entity_id} ${c.field}` : c.entity === "profile" ? c.field : c.entity_id;
  return `${what} ${field ?? ""}`.trim();
}

export function ChangeChip({ change }: { change: ChangeSummary }) {
  const [state, setState] = useState<"idle" | "busy" | "undone" | string>("idle");
  const undo = () => {
    setState("busy");
    undoChange(change.id).then(() => setState("undone")).catch((e) => setState(`Couldn't undo: ${e.message}`));
  };
  const value = change.entity === "file" ? "updated" : `${show(change.before)} → ${show(change.after)}`;
  return (
    <div className="agent-chip" data-agent-ui>
      <span>Changed {changeLabel(change)}: {value}</span>
      {change.undoable && (state === "undone" ? <span className="agent-chip-done">Undone</span>
        : <button className="linkish" disabled={state === "busy"} onClick={undo}>Undo</button>)}
      {state.startsWith("Couldn't") && <span role="alert">{state}</span>}
    </div>
  );
}

function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) =>
        b.type === "thinking" ? (b.thinking.trim() && (
          <details key={i} className="agent-thinking"><summary>Thinking</summary><p>{b.thinking}</p></details>
        )) : b.type === "text" ? (b.text.trim() && <div key={i} className="agent-text">{b.text.trim()}</div>)
          : <div key={i} className="agent-tool">Using {b.name.replaceAll("_", " ")}</div>)}
    </>
  );
}

function ToolResult({ msg }: { msg: Message }) {
  const d = msg.details ?? {};
  const widget = d.widget === "secret" ? <SecretWidget keyName={String(d.key)} reason={String(d.reason ?? "")} />
    : d.widget === "upload" ? <UploadWidget reason={String(d.reason ?? "")} />
    : d.widget === "confirm" ? <ConfirmWidget confirmation={d.confirmation as never} /> : null;
  return (
    <>
      {(d.changes ?? []).map((c) => <ChangeChip key={c.id} change={c} />)}
      {widget}
      {msg.isError && !widget && <div className="agent-tool agent-tool-error">That didn't work: {textOf(msg).slice(0, 200)}</div>}
    </>
  );
}

export function EntryView({ entry }: { entry: Entry }) {
  const msg = entry.model?.[0];
  const turn = userTurn(entry);
  if (turn) {
    return (
      <div className="agent-msg agent-user" data-entry={entry.id}>
        {turn.context && <div className="agent-about">About: {turn.context.heading || turn.context.label || turn.context.anchor || turn.context.text.slice(0, 60)}</div>}
        <div>{turn.question}</div>
      </div>
    );
  }
  if (!msg) return entry.kind === "pi.compaction" ? <div className="agent-tool">Earlier messages were summarized.</div> : null;
  if (entry.kind === "pi.assistant" && Array.isArray(msg.content)) {
    return <div className="agent-msg agent-assistant" data-entry={entry.id}><Blocks blocks={msg.content} /></div>;
  }
  if (entry.kind === "pi.tool-result") return <ToolResult msg={msg} />;
  return null;
}

export function Thread({ entries, partial, running, toolsRunning, focus }: {
  entries: Entry[]; partial: Message | null; running: boolean; toolsRunning?: string[]; focus?: number | null;
}) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const target = focus != null ? box.current?.querySelector(`[data-entry="${focus}"]`) : null;
    (target ?? end.current)?.scrollIntoView?.({ block: target ? "center" : "end" });
  }, [entries.length, partial, focus]);
  return (
    <div className="agent-thread" ref={box} aria-live="polite">
      {entries.map((e) => <EntryView key={e.id} entry={e} />)}
      {partial && Array.isArray(partial.content) && (
        <div className="agent-msg agent-assistant"><Blocks blocks={partial.content} /></div>
      )}
      {running && !partial && (
        <div className="agent-tool">{toolsRunning?.length ? `Using ${toolsRunning[0]!.replaceAll("_", " ")}…` : "Thinking…"}</div>
      )}
      <div ref={end} />
    </div>
  );
}

/** The composer under a thread. */
export function Composer({ placeholder, onSend, autoFocus }: { placeholder: string; onSend: (text: string) => void; autoFocus?: boolean }) {
  const [text, setText] = useState("");
  const send = () => {
    const t = text.trim();
    if (!t) return;
    onSend(t);
    setText("");
  };
  return (
    <div className="agent-composer">
      <textarea aria-label="Message the agent" placeholder={placeholder} value={text} rows={2} autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
      <button className="btn btn-primary" onClick={send} disabled={!text.trim()}>Send</button>
    </div>
  );
}
