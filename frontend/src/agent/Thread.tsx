// A session's transcript, rendered like pi's: the user's prompts, the agent's markdown, thinking (Ctrl+T shows or
// hides it), and every tool call with its arguments and result, output collapsed to a few lines (Ctrl+O expands).
// A change a tool made shows a "Changed X: a → b · Undo" line; widgets (secret, upload, Confirm) appear in place.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ChangeSummary } from "@jobdash/agent-protocol";
import { undoChange } from "./client.ts";
import Markdown from "./Markdown.tsx";
import { textOf, userTurn, type Block, type Entry, type ImageBlock, type LiveTool, type Message, type ToolCallBlock } from "./state.ts";
import { ConfirmWidget, SecretWidget, UploadWidget } from "./Widgets.tsx";

const ENTITY: Record<string, string> = {
  profile: "Profile", qbank: "Saved answer", qa_row: "Application answer", setting: "Setting", config: "Setting",
  job: "Job", file: "File",
};
const COLLAPSED_LINES = 6;

export function show(v: unknown): string {
  if (v == null || v === "") return "—";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 60 ? `${s.slice(0, 57)}…` : s;
}

export function changeLabel(c: Pick<ChangeSummary, "entity" | "entity_id" | "field">): string {
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

export interface ViewOptions {
  expandTools: boolean;
  showThinking: boolean;
}

const DEFAULT_VIEW: ViewOptions = { expandTools: false, showThinking: false };

function argsLine(args: Record<string, unknown> | undefined): string {
  if (!args || !Object.keys(args).length) return "";
  return Object.entries(args).map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v.length > 80 ? `${v.slice(0, 77)}…` : v) : JSON.stringify(v)}`).join(" ");
}

function Output({ text, expand }: { text: string; expand: boolean }) {
  const [open, setOpen] = useState(false);
  const all = text.replace(/\s+$/, "").split("\n");
  if (!text.trim()) return null;
  const full = expand || open;
  const shown = full ? all : all.slice(0, COLLAPSED_LINES);
  return (
    <div className="pi-tool-out">
      <pre>{shown.join("\n")}</pre>
      {all.length > COLLAPSED_LINES && (
        <button className="pi-more" onClick={() => setOpen(!open)}>
          {full ? "▴ collapse" : `… ${all.length - COLLAPSED_LINES} more lines (click or Ctrl+O)`}
        </button>
      )}
    </div>
  );
}

function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function ToolBlock({ call, result, live, view }: { call: ToolCallBlock; result?: Message; live?: LiveTool; view: ViewOptions }) {
  const d = result?.details ?? {};
  const widget = d.widget === "secret" ? <SecretWidget keyName={String(d.key)} reason={String(d.reason ?? "")} />
    : d.widget === "upload" ? <UploadWidget reason={String(d.reason ?? "")} />
    : d.widget === "confirm" ? <ConfirmWidget confirmation={d.confirmation as never} /> : null;
  const status = result ? (result.isError ? "error" : "done") : "running";
  return (
    <div className={`pi-tool pi-tool-${status}`} data-tool={call.name}>
      <div className="pi-tool-head">
        <span className="pi-tool-name">{call.name}</span>
        <span className="pi-tool-args">{argsLine(call.arguments ?? live?.args)}</span>
        {status === "running" && <span className="pi-spin" aria-label="running">⠋</span>}
      </div>
      {!widget && <Output text={result ? pretty(textOf(result)) : live?.output ?? ""} expand={view.expandTools} />}
      {(d.changes ?? []).map((c) => <ChangeChip key={c.id} change={c} />)}
      {widget}
    </div>
  );
}

function Thinking({ text, view }: { text: string; view: ViewOptions }) {
  if (!text.trim()) return null;
  return view.showThinking
    ? <div className="pi-thinking">{text.trim()}</div>
    : <div className="pi-thinking pi-thinking-folded">Thinking… <span>(Ctrl+T to show)</span></div>;
}

function Assistant({ msg, results, live, view, id }: { msg: Message; results: Map<string, Message>; live: LiveTool[]; view: ViewOptions; id?: number }) {
  const blocks = Array.isArray(msg.content) ? msg.content : [{ type: "text", text: msg.content } as Block];
  return (
    <div className="pi-assistant" data-entry={id}>
      {blocks.map((b, i) =>
        b.type === "thinking" ? <Thinking key={i} text={b.thinking} view={view} />
          : b.type === "text" ? (b.text.trim() ? <Markdown key={i} text={b.text.trim()} /> : null)
          : b.type === "toolCall" ? <ToolBlock key={i} call={b} result={results.get(b.id)} live={live.find((t) => t.id === b.id)} view={view} />
          : null)}
      {(msg as { stopReason?: string }).stopReason === "aborted" && <div className="pi-note pi-error">Aborted</div>}
      {(msg as { errorMessage?: string }).errorMessage && <div className="pi-note pi-error">{(msg as { errorMessage?: string }).errorMessage}</div>}
    </div>
  );
}

const pictures = (entry: Entry): ImageBlock[] => {
  const c = entry.model?.[0]?.content;
  return Array.isArray(c) ? c.filter((b): b is ImageBlock => b.type === "image") : [];
};

function User({ entry }: { entry: Entry }) {
  const turn = userTurn(entry)!;
  return (
    <div className="pi-user" data-entry={entry.id}>
      {turn.context && <div className="agent-about">↳ {turn.context.heading || turn.context.label || turn.context.anchor || turn.context.text.slice(0, 60)}</div>}
      <div className="pi-user-text">{turn.question}</div>
      {pictures(entry).length > 0 && (
        <div className="pi-user-images">
          {pictures(entry).map((p, i) => <img key={i} src={`data:${p.mimeType};base64,${p.data}`} alt={`Attached image ${i + 1}`} />)}
        </div>
      )}
    </div>
  );
}

export function Thread({ entries, partial, running, toolsRunning, live = [], focus, view = DEFAULT_VIEW, notes, forkAt }: {
  entries: Entry[]; partial: Message | null; running: boolean; toolsRunning?: string[]; live?: LiveTool[];
  focus?: number | null; view?: ViewOptions; notes?: React.ReactNode;
  /** In a branch: the last shared entry, after which a divider marks where this branch begins. */
  forkAt?: number;
}) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  // Follow new output only while the reader is at the bottom, as pi does. Any move up (wheel, touch, keys, the
  // scrollbar) lets go at once; coming back to the bottom follows again. Our own scrolling never counts as the reader's.
  const stick = useRef(true);
  const ours = useRef(false);
  const [away, setAway] = useState(false);
  const scrollerOf = () => (box.current?.closest(".pi-scroll") as HTMLElement | null) ?? box.current;
  useEffect(() => {
    const scroller = scrollerOf();
    if (!scroller) return undefined;
    const atBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 4;
    const letGo = () => { stick.current = false; setAway(true); };
    const onScroll = () => {
      if (ours.current) { ours.current = false; return; }
      if (atBottom()) { stick.current = true; setAway(false); } else letGo();
    };
    const onWheel = (e: WheelEvent) => { if (e.deltaY < 0) letGo(); };
    const onKey = (e: KeyboardEvent) => { if (["PageUp", "ArrowUp", "Home"].includes(e.key)) letGo(); };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    scroller.addEventListener("wheel", onWheel, { passive: true });
    scroller.addEventListener("touchmove", letGo, { passive: true });
    scroller.addEventListener("keydown", onKey);
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("wheel", onWheel);
      scroller.removeEventListener("touchmove", letGo);
      scroller.removeEventListener("keydown", onKey);
    };
  }, []);
  // A jump (from /tree, a popover, an Update) waits until its message has loaded, then puts it at the top.
  const pending = useRef<number | null>(null);
  useEffect(() => { if (focus != null) { pending.current = focus; stick.current = false; } }, [focus]);
  const follow = () => {
    const scroller = scrollerOf();
    if (!scroller || scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 1) return;
    ours.current = true;
    scroller.scrollTop = scroller.scrollHeight;            // only this box moves, never the page around it
  };
  useLayoutEffect(() => {
    if (pending.current != null) {
      const el = box.current?.querySelector(`[data-entry="${pending.current}"]`);
      if (el) {
        el.scrollIntoView?.({ block: "start" });
        pending.current = null;
        setAway(true);
      }
      return;
    }
    if (stick.current) follow();
  });
  const toLatest = () => { stick.current = true; setAway(false); follow(); };
  const results = new Map<string, Message>();
  for (const e of entries) {
    const m = e.model?.[0];
    if (e.kind === "pi.tool-result" && m?.toolCallId) results.set(m.toolCallId, m);
  }
  const renderEntry = (e: Entry, msg: Message | undefined) => {
    if (e.kind === "pi.user") return <User key={e.id} entry={e} />;
    if (e.kind === "pi.assistant" && msg) return <Assistant key={e.id} id={e.id} msg={msg} results={results} live={live} view={view} />;
    if (e.kind === "pi.compaction") return <div key={e.id} className="pi-note">── context compacted: earlier messages are summarized ──</div>;
    if (e.kind === "pi.reset") return <div key={e.id} className="pi-note">── new context ──</div>;
    return null;
  };
  return (
    <div className="agent-thread pi-thread" ref={box} aria-live="polite">
      {entries.map((e, i) => {
        const msg = e.model?.[0];
        if (forkAt !== undefined && i > 0 && entries[i - 1]!.id <= forkAt && e.id > forkAt) {
          return [<div key={`fork-${e.id}`} className="pi-note pi-forked">── this branch starts here; above is shared with the session it came from ──</div>,
            renderEntry(e, msg)];
        }
        return renderEntry(e, msg);
      })}

      {partial && <Assistant msg={partial} results={results} live={live} view={view} />}
      {running && !partial && !live.length && (
        <div className="pi-note pi-working">{toolsRunning?.length ? `Running ${toolsRunning[0]}…` : "Working…"}</div>
      )}
      {notes}
      <div ref={end} />
      {away && running && <button className="pi-latest" onClick={toLatest}>↓ Latest</button>}
    </div>
  );
}

/** The popover's composer. */
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
