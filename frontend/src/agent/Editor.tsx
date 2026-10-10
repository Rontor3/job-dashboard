// The Agent tab's editor, with pi's keys: Enter sends (while the agent works it steers the current task),
// Alt+Enter queues a follow-up, Shift+Enter adds a line, Up/Down walk prompt history, Alt+Up takes queued messages
// back, Esc stops the agent, Shift+Tab cycles the thinking level, Ctrl+L picks a model, Ctrl+C clears.
// Typing `/` opens the command menu: Up/Down choose, Tab completes, Enter runs. Pictures can be pasted, dropped or
// attached (up to four); the box grows with what you type.
import { forwardRef, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import type { CommandInfo } from "@jobdash/agent-protocol";
import type { Picture } from "./client.ts";

const MAX_PICTURES = 4;
const MAX_BYTES = 5 * 1024 * 1024;
const TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const MAX_HEIGHT = 0.4;                                    // of the window

function readPicture(file: File): Promise<Picture & { name: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, mimeType: file.type, data: String(reader.result).split(",")[1] ?? "" });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

const HISTORY_KEY = "agent-prompt-history";
const HISTORY_MAX = 100;

function loadHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function saveHistory(h: string[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(-HISTORY_MAX)));
  } catch {
    // private mode: history lasts this page only
  }
}

export interface EditorHandle {
  focus(): void;
  setText(text: string): void;
}

export interface EditorProps {
  commands: CommandInfo[];
  running: boolean;
  thinkingLevel?: string;
  onSubmit(text: string, mode: "steer" | "followUp", images?: Picture[]): void;
  onCommand(name: string, args: string): void;
  onStop(): void;
  onTakeBack(): void;
  onCycleThinking(): void;
  onPickModel(): void;
}

export const Editor = forwardRef<EditorHandle, EditorProps>(function Editor(props, ref) {
  const { commands, running, thinkingLevel } = props;
  const [text, setText] = useState("");
  const [sel, setSel] = useState(0);
  const [menuClosed, setMenuClosed] = useState(false);
  const history = useRef<string[]>(loadHistory());
  const at = useRef<number | null>(null);          // position while walking history
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [pics, setPics] = useState<(Picture & { name: string })[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  const fit = () => {                                      // one line when empty, growing with the text
    const el = area.current;
    if (!el || !el.offsetParent) return;                   // hidden (another tab): measure when shown
    el.style.height = "auto";
    const max = Math.round(window.innerHeight * MAX_HEIGHT);
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  };
  useLayoutEffect(fit, [text]);
  useLayoutEffect(() => {
    const el = area.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => { if (!el.style.height || el.style.height === "auto") fit(); });
    ro.observe(el);
    window.addEventListener("resize", fit);
    return () => { ro.disconnect(); window.removeEventListener("resize", fit); };
  }, []);

  const addFiles = async (files: File[]) => {
    setProblem(null);
    const ok = files.filter((f) => TYPES.includes(f.type));
    if (ok.length < files.length) setProblem("Only PNG, JPEG, WebP or GIF pictures can be attached.");
    const small = ok.filter((f) => f.size <= MAX_BYTES);
    if (small.length < ok.length) setProblem("Pictures must be under 5 MB.");
    const room = MAX_PICTURES - pics.length;
    if (small.length > room) setProblem(`Up to ${MAX_PICTURES} pictures per message.`);
    const read = await Promise.all(small.slice(0, Math.max(0, room)).map(readPicture));
    setPics((p) => [...p, ...read].slice(0, MAX_PICTURES));
  };
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = [...e.clipboardData.items].filter((i) => i.kind === "file").map((i) => i.getAsFile()).filter((f): f is File => !!f);
    if (files.length) { e.preventDefault(); void addFiles(files); }
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    void addFiles([...e.dataTransfer.files]);
  };

  useImperativeHandle(ref, () => ({
    focus: () => area.current?.focus(),
    setText: (t) => { setText(t); setTimeout(() => area.current?.focus(), 0); },
  }), []);

  const slash = /^\/(\S*)$/.exec(text);
  const matches = useMemo(() => (slash && !menuClosed
    ? commands.filter((c) => c.name.startsWith(slash[1]!)).concat(commands.filter((c) => !c.name.startsWith(slash[1]!) && c.name.includes(slash[1]!)))
    : []), [commands, slash?.[1], menuClosed]);
  const menu = matches.length > 0;

  const remember = (t: string) => {
    const h = history.current.filter((x) => x !== t);
    h.push(t);
    history.current = h.slice(-HISTORY_MAX);
    saveHistory(history.current);
  };

  const submit = (mode: "steer" | "followUp") => {
    const t = text.trim() || (pics.length ? "What's in this picture?" : "");
    if (!t) return;
    remember(t);
    at.current = null;
    setText("");
    setMenuClosed(false);
    const cmd = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(t);
    if (cmd) props.onCommand(cmd[1]!, (cmd[2] ?? "").trim());
    else {
      props.onSubmit(t, mode, pics.map(({ data, mimeType }) => ({ data, mimeType })));
      setPics([]);
      setProblem(null);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (menu) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSel((sel + 1) % matches.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setSel((sel - 1 + matches.length) % matches.length); return; }
      if (e.key === "Tab" && !e.shiftKey) { e.preventDefault(); setText(`/${matches[sel]!.name} `); setSel(0); return; }
      if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        const c = matches[sel]!;
        remember(`/${c.name}`);
        setText("");
        setSel(0);
        props.onCommand(c.name, "");
        return;
      }
      if (e.key === "Escape") { e.preventDefault(); setMenuClosed(true); return; }
    }
    if (e.key === "Enter" && e.altKey) { e.preventDefault(); submit("followUp"); return; }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit("steer"); return; }
    if (e.key === "Escape") { e.preventDefault(); if (running) props.onStop(); return; }
    if (e.key === "ArrowUp" && e.altKey) { e.preventDefault(); props.onTakeBack(); return; }
    if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); props.onCycleThinking(); return; }
    if (e.ctrlKey && !e.metaKey && e.key.toLowerCase() === "l") { e.preventDefault(); props.onPickModel(); return; }
    if (e.ctrlKey && !e.metaKey && e.key.toLowerCase() === "c" && area.current?.selectionStart === area.current?.selectionEnd) {
      e.preventDefault();
      setText("");
      return;
    }
    const el = area.current!;
    const h = history.current;
    if (e.key === "ArrowUp" && el.selectionStart === 0 && h.length) {
      e.preventDefault();
      at.current = at.current === null ? h.length - 1 : Math.max(0, at.current - 1);
      setText(h[at.current]!);
      return;
    }
    if (e.key === "ArrowDown" && at.current !== null && el.selectionEnd === text.length) {
      e.preventDefault();
      at.current = at.current + 1 >= h.length ? null : at.current + 1;
      setText(at.current === null ? "" : h[at.current]!);
    }
  };

  return (
    <div className={`pi-editor pi-think-${thinkingLevel ?? "off"}`} onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
      {menu && (
        <ul className="pi-menu" role="listbox" aria-label="Commands">
          {matches.slice(0, 12).map((c, i) => (
            <li key={c.name} role="option" aria-selected={i === sel} onMouseDown={(e) => { e.preventDefault(); setSel(i); setText(`/${c.name} `); area.current?.focus(); }}>
              <span className="pi-menu-name">/{c.name}{c.args ? <span className="pi-menu-args"> {c.args}</span> : null}</span>
              <span className="pi-menu-desc">{c.kind === "template" ? `[prompt] ${c.description}` : c.description}</span>
            </li>
          ))}
        </ul>
      )}
      {pics.length > 0 && (
        <ul className="pi-pics" aria-label="Attached pictures">
          {pics.map((p, i) => (
            <li key={i}>
              <img src={`data:${p.mimeType};base64,${p.data}`} alt={p.name || `Picture ${i + 1}`} />
              <button aria-label={`Remove ${p.name || `picture ${i + 1}`}`} onClick={() => setPics(pics.filter((_, k) => k !== i))}>×</button>
            </li>
          ))}
        </ul>
      )}
      {problem && <p className="pi-pics-note" role="status">{problem}</p>}
      <div className="pi-input">
        <textarea ref={area} aria-label="Message the agent" value={text} rows={1}
          placeholder={running ? "Enter steers the agent · Alt+Enter queues a follow-up · Esc stops" : "Message, or / for commands · paste a picture"}
          onChange={(e) => { setText(e.target.value); setSel(0); setMenuClosed(false); at.current = null; }} onKeyDown={onKey} onPaste={onPaste} autoFocus />
        <button type="button" className="pi-attach" aria-label="Attach a picture" title="Attach a picture" onClick={() => picker.current?.click()}>＋</button>
        <input ref={picker} type="file" accept={TYPES.join(",")} multiple hidden aria-hidden="true"
          onChange={(e) => { void addFiles([...(e.target.files ?? [])]); e.target.value = ""; }} />
      </div>
    </div>
  );
});
