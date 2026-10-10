// The Agent tab: a pi session in the browser. The startup header lists what the agent loaded; the transcript shows
// prompts, answers, thinking and tool calls; the editor takes messages and slash commands; the footer shows the
// session, model, thinking level, context use, tokens and cost. Commands that need the harness run in the agent
// service (commands.ts); copy, export, resume, tree, hotkeys and changes run here.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { CommandInfo, SessionStats } from "@jobdash/agent-protocol";
import { useAgent } from "./AgentProvider.tsx";
import ChangeHistory from "./ChangeHistory.tsx";
import { fetchCommands, fetchModels, fetchStats, runCommand } from "./client.ts";
import { Editor, type EditorHandle } from "./Editor.tsx";
import { HotkeysPanel, Panel, Picker, StatsPanel, treeItems, type PickItem } from "./Overlays.tsx";
import { textOf, totalUsage, userTurn, type Entry } from "./state.ts";
import { Thread, type ViewOptions } from "./Thread.tsx";
import TeamRail, { MISSIONS } from "./TeamRail.tsx";
import { SecretWidget } from "./Widgets.tsx";

const LEVELS = ["off", "low", "medium", "high", "xhigh"];
const CLIENT_COMMANDS: CommandInfo[] = [];     // all are listed by the service; kept for an offline editor

type Overlay =
  | { kind: "models"; items: PickItem[] }
  | { kind: "sessions" | "tree" | "fork"; items: PickItem[] }
  | { kind: "stats"; stats: SessionStats }
  | { kind: "hotkeys" | "changes" | "login" | "settings" };

interface Note { id: number; text: string; error?: boolean }

const k = (x: number) => (x >= 1000 ? `${(x / 1000).toFixed(x >= 10_000 ? 0 : 1)}k` : String(Math.round(x)));

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** /export: the transcript as markdown (default) or one JSON entry per line. */
export function exportText(entries: Entry[], title: string, format: "md" | "jsonl"): string {
  if (format === "jsonl") return entries.map((e) => JSON.stringify(e)).join("\n") + "\n";
  const out = [`# ${title}`, ""];
  for (const e of entries) {
    const m = e.model?.[0];
    if (!m) continue;
    if (e.kind === "pi.user") out.push(`## You`, "", userTurn(e)?.question ?? textOf(m), "");
    else if (e.kind === "pi.assistant" && Array.isArray(m.content)) {
      out.push("## Agent", "");
      for (const b of m.content) {
        if (b.type === "text" && b.text.trim()) out.push(b.text.trim(), "");
        if (b.type === "toolCall") out.push(`> tool \`${b.name}\` ${JSON.stringify(b.arguments)}`, "");
      }
    } else if (e.kind === "pi.tool-result") out.push("```", textOf(m).slice(0, 2000), "```", "");
  }
  return out.join("\n");
}

export default function AgentTab() {
  const agent = useAgent();
  const { sessions, thread } = agent;
  const active = sessions.active;
  const current = sessions.items.find((s) => s.id === active);
  const title = current?.title ?? "New session";
  const profile = current?.profile;
  const [commands, setCommands] = useState<CommandInfo[]>(CLIENT_COMMANDS);
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [view, setView] = useState<ViewOptions>({ expandTools: false, showThinking: false });
  const editor = useRef<EditorHandle>(null);
  const noteId = useRef(0);

  const note = useCallback((text: string, error = false) => {
    if (text) setNotes((n) => [...n.slice(-30), { id: ++noteId.current, text, error }]);
  }, []);
  const close = () => { setOverlay(null); setTimeout(() => editor.current?.focus(), 0); };

  useEffect(() => { fetchCommands().then((c) => setCommands(c.commands)).catch(() => {}); }, []);
  const loadStats = useCallback(() => { if (active) fetchStats(active).then(setStats).catch(() => {}); }, [active]);
  useEffect(() => { setNotes([]); loadStats(); }, [active, loadStats]);
  useEffect(() => { if (!thread.running) loadStats(); }, [thread.running, thread.entries.length, loadStats]);

  // Ctrl+O and Ctrl+T work anywhere in the tab, as in pi.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.metaKey) return;
      if (e.key.toLowerCase() === "o") { e.preventDefault(); setView((v) => ({ ...v, expandTools: !v.expandTools })); }
      if (e.key.toLowerCase() === "t") { e.preventDefault(); setView((v) => ({ ...v, showThinking: !v.showThinking })); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const server = async (name: string, args = "", extra: Record<string, unknown> = {}) => {
    if (!active) return undefined;
    try {
      const r = await runCommand(active, name, args, extra);
      if (r.message) note(r.message);
      if (r.session) await agent.refreshSessions();
      if (name === "name") await agent.refreshSessions();
      loadStats();
      return r;
    } catch (e) {
      note((e as Error).message, true);
      return undefined;
    }
  };

  const pickModel = async () => {
    try {
      const { default: dflt, available } = await fetchModels();
      const current = thread.agent.model?.modelId ?? stats?.model;
      const ids = [...new Set([dflt, ...available, ...(current ? [current] : [])])];
      setOverlay({ kind: "models", items: ids.map((id) => ({ id, label: id, hint: id === dflt ? "app default (LLM_MODEL)" : undefined, current: id === current })) });
    } catch (e) {
      note(`Couldn't list models: ${(e as Error).message}`, true);
    }
  };

  const cycleThinking = () => {
    const cur = thread.agent.thinkingLevel ?? stats?.thinkingLevel ?? "off";
    void server("thinking", LEVELS[(LEVELS.indexOf(cur) + 1) % LEVELS.length]!);
  };

  const userEntries = thread.entries.filter((e) => e.kind === "pi.user");

  const run = async (name: string, args: string) => {
    switch (name) {
      case "new": await agent.newSession(); return;
      case "resume":
        setOverlay({ kind: "sessions", items: sessions.items.map((s) => ({ id: s.id, label: s.title, hint: new Date(s.createdAt).toLocaleString(), current: s.id === active })) });
        return;
      case "tree": setOverlay({ kind: "tree", items: treeItems(sessions.items, active) }); return;
      case "fork":
        if (!userEntries.length) { note("Nothing to fork from yet", true); return; }
        setOverlay({ kind: "fork", items: [...userEntries].reverse().map((e) => ({ id: String(e.id), label: userTurn(e)?.question.split("\n")[0]!.slice(0, 120) ?? "" })) });
        return;
      case "model": if (args) await server("model", args); else await pickModel(); return;
      case "session": if (active) setOverlay({ kind: "stats", stats: await fetchStats(active) }); return;
      case "hotkeys": case "changes": case "login": case "settings": setOverlay({ kind: name }); return;
      case "copy": {
        const last = [...thread.entries].reverse().find((e) => e.kind === "pi.assistant" && textOf(e.model?.[0]).trim());
        if (!last) { note("No agent message to copy", true); return; }
        try {
          await navigator.clipboard.writeText(textOf(last.model?.[0]).trim());
          note("Copied the last agent message");
        } catch {
          note("The browser didn't allow copying", true);
        }
        return;
      }
      case "export": {
        const fmt = args === "jsonl" ? "jsonl" : "md";
        download(`agent-session-${title.replace(/[^\w-]+/g, "-").slice(0, 40)}.${fmt}`, exportText(thread.entries, title, fmt),
          fmt === "md" ? "text/markdown" : "application/x-ndjson");
        note(`Exported ${thread.entries.length} entries as ${fmt}`);
        return;
      }
      default: await server(name, args);
    }
  };

  const picked = async (o: Overlay, item: PickItem) => {
    close();
    if (o.kind === "models") await server("model", item.id);
    else if (o.kind === "sessions" || o.kind === "tree") await agent.openSession(item.id);
    else if (o.kind === "fork") {
      // pi's /fork: a new session with everything before that message, and the message back in the editor.
      const i = thread.entries.findIndex((e) => String(e.id) === item.id);
      const before = i > 0 ? thread.entries[i - 1]!.id : undefined;
      const text = userTurn(thread.entries[i]!)?.question ?? "";
      if (before === undefined) await agent.newSession();
      else await server("fork", "", { at: before });
      editor.current?.setText(text);
    }
  };

  const u = totalUsage(thread.usage);
  const ctxWindow = stats?.contextWindow ?? 0;
  const live = thread.running && thread.lastUsage ? (thread.lastUsage.input ?? 0) + (thread.lastUsage.cacheRead ?? 0) : 0;
  const ctxTokens = live || stats?.contextTokens || 0;
  const model = thread.agent.model?.modelId ?? stats?.model ?? "…";
  const level = thread.agent.thinkingLevel ?? stats?.thinkingLevel ?? "off";
  const queued = thread.inbox.length;

  let panel: ReactNode = null;
  if (overlay) {
    if (overlay.kind === "stats") panel = <StatsPanel s={overlay.stats} onClose={close} />;
    else if (overlay.kind === "hotkeys") panel = <HotkeysPanel onClose={close} />;
    else if (overlay.kind === "changes") panel = <Panel title="/changes" onClose={close}><ChangeHistory /></Panel>;
    else if (overlay.kind === "login") panel = (
      <Panel title="/login" onClose={close}>
        <SecretWidget keyName="LLM_API_KEY" reason="The key for the configured LLM endpoint (LLM_BASE_URL). It goes straight to .env." onDone={() => note("LLM_API_KEY set")} />
      </Panel>
    );
    else if (overlay.kind === "settings") panel = (
      <Panel title="/settings" onClose={close}>
        <table className="pi-kv"><tbody>
          <tr><th>Model</th><td>{model} <span className="pi-dim">(/model, Ctrl+L; the app default is LLM_MODEL)</span></td></tr>
          <tr><th>Thinking</th><td>{level} <span className="pi-dim">(/thinking, Shift+Tab)</span></td></tr>
          <tr><th>Context window</th><td>{ctxWindow ? k(ctxWindow) : "?"} tokens <span className="pi-dim">(LLM_CONTEXT_WINDOW)</span></td></tr>
          <tr><th>Compaction</th><td>automatic near the context limit; /compact to run it now</td></tr>
          <tr><th>Tool output</th><td>{view.expandTools ? "expanded" : "collapsed"} <span className="pi-dim">(Ctrl+O)</span></td></tr>
          <tr><th>Thinking blocks</th><td>{view.showThinking ? "shown" : "hidden"} <span className="pi-dim">(Ctrl+T)</span></td></tr>
          <tr><th>Instructions</th><td>docs/agent/system.md + data/agent/user.md + data/agent/about-me.md <span className="pi-dim">(/reload after editing)</span></td></tr>
          <tr><th>Profiles</th><td>docs/agent/profiles/&lt;name&gt;.md, yours in data/agent/profiles/ <span className="pi-dim">(/profile)</span></td></tr>
          <tr><th>Prompt templates</th><td>data/agent/prompts/&lt;name&gt;.md → /&lt;name&gt; <span className="pi-dim">($1…$9, $@)</span></td></tr>
        </tbody></table>
      </Panel>
    );
    else if ("items" in overlay) panel = (
      <Picker title={overlay.kind === "models" ? "/model" : overlay.kind === "fork" ? "/fork — pick a message to branch before" : `/${overlay.kind === "sessions" ? "resume" : "tree"}`}
        items={overlay.items} onPick={(i) => void picked(overlay, i)} onClose={close} />
    );
  }

  const empty = thread.entries.length === 0 && !thread.partial && !thread.running;

  return (
    <div className="agent-home">
    <TeamRail />
    <section aria-label="Agent" className="pi-tab">
      <div className="pi-scroll">
        <div className="pi-header">
          <div>
            <strong>{profile ? `${profile[0]!.toUpperCase()}${profile.slice(1)}` : "jobdash agent"}</strong>
            {" "}<span className="pi-dim">· pi-durable · /profile to switch, / for commands, /hotkeys for keys</span>
          </div>
          {stats && (
            <div className="pi-dim">
              [Context] {stats.prompt.filter((p) => p.loaded).map((p) => p.file.replace(/^.*\/(docs|data)\//, "$1/")).join(", ")}
              {"  "}[Tools] {stats.tools.length}
              {commands.some((c) => c.kind === "template") && <>{"  "}[Prompts] {commands.filter((c) => c.kind === "template").map((c) => `/${c.name}`).join(" ")}</>}
            </div>
          )}
        </div>
        {empty && (
          <div className="agent-start">
            <h2>What should the agents do?</h2>
            <p>Type anything below, or hand off one of these. You'll only be asked what nobody else can answer.</p>
            <div className="agent-start-grid">
              {MISSIONS.map((m) => (
                <button key={m.title} className="agent-start-card" onClick={() => void agent.start(m.message, { profile: m.profile })}>
                  <strong>{m.title}</strong><span>{m.hint}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <Thread entries={thread.entries} partial={thread.partial} running={thread.running} toolsRunning={thread.toolsRunning}
          live={thread.live} focus={agent.focusEntry} view={view}
          notes={<>
            {thread.retry && <div className="pi-note pi-error">Retrying: {thread.retry}</div>}
            {thread.compacting && <div className="pi-note">Compacting the context…</div>}
            {thread.failure && <div className="pi-note pi-error">Failed: {thread.failure}</div>}
            {agent.error && <div className="pi-note pi-error">{agent.error}</div>}
            {notes.map((n) => <div key={n.id} className={n.error ? "pi-note pi-error" : "pi-note"}>{n.text}</div>)}
          </>} />
      </div>
      {panel}
      <Editor ref={editor} commands={commands} running={thread.running} thinkingLevel={level}
        onSubmit={(t, mode) => void agent.ask(t, undefined, mode)}
        onCommand={(n, a) => void run(n, a)}
        onStop={() => void agent.takeBack().then((back) => {           // queued messages return to the editor
          if (back.length) editor.current?.setText(back.join("\n"));
          return agent.stop();
        })}
        onTakeBack={() => void agent.takeBack().then((back) => { if (back.length) editor.current?.setText(back.join("\n")); else note("Nothing queued"); })}
        onCycleThinking={cycleThinking} onPickModel={() => void pickModel()} />
      <footer className="pi-footer">
        <div className="pi-footer-line">
          <span>{title}</span>
          <span className="pi-dim">{thread.running ? (queued ? `working · ${queued} queued` : "working") : "idle"}</span>
        </div>
        <div className="pi-footer-line pi-dim">
          <span>↑{k(u.input)} ↓{k(u.output)}{u.cacheRead ? ` R${k(u.cacheRead)}` : ""}{u.cacheWrite ? ` W${k(u.cacheWrite)}` : ""} ${u.cost.toFixed(3)}
            {ctxWindow ? `  ${((100 * ctxTokens) / ctxWindow).toFixed(1)}%/${k(ctxWindow)}` : ""}</span>
          <span>{profile ? `${profile} • ` : ""}{model} • {level === "off" ? "thinking off" : level}</span>
        </div>
      </footer>
    </section>
    </div>
  );
}
