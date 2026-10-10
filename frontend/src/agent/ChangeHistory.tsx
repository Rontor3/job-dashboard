// /changes: every change to your data, by you or the agent, newest first, in words, with Undo where it applies.
// Other things that happened (a job queued, a Refresh started) are hidden unless asked for.
import { useCallback, useEffect, useState } from "react";
import { fetchChanges, undoChange, type ChangeRow } from "./client.ts";
import { changeLabel, show } from "./Thread.tsx";

const WHO = { agent: "Agent", ui: "You" } as const;

const ACTIONS: [RegExp, string][] = [
  [/^POST \/api\/queue\/start/, "Started the apply queue"],
  [/^POST \/api\/queue\/pause/, "Paused the apply queue"],
  [/^POST \/api\/queue(\?|$)/, "Added a job to the apply queue"],
  [/^DELETE \/api\/queue/, "Removed a job from the apply queue"],
  [/^POST \/api\/refresh/, "Started Refresh"],
  [/^POST \/api\/hiring\/refresh/, "Started the hiring-post refresh"],
  [/^POST \/api\/mail-scan/, "Scanned mail"],
  [/^POST \/api\/jobs\/(\d+)\/apply-agent/, "Ran the apply agent on job #$1"],
  [/^POST \/api\/jobs\/(\d+)\/skip/, "Skipped job #$1"],
  [/^POST \/api\/application-qa\/(\d+)\/review/, "Reviewed a guessed answer"],
  [/^POST \/api\/jobs\/(\d+)\/questions\/\d+\/reply/, "Answered a question for job #$1"],
  [/^POST \/api\/hiring\/posts\/(\d+)\/dismiss/, "Dismissed a hiring post"],
  [/^POST \/api\/hiring\/posts\/(\d+)\/promote/, "Researched a hiring post's company"],
];

export function describe(c: ChangeRow): string {
  if (c.entity === "action") {
    const line = `${c.field} ${c.entity_id}`;
    for (const [re, text] of ACTIONS) {
      const m = re.exec(line);
      if (m) return text.replace("$1", m[1] ?? "");
    }
    return line;
  }
  if (c.entity === "secret") return `Set ${c.entity_id}`;
  if (c.entity === "file") return `${c.entity_id === "current_resume" ? "Uploaded the résumé" : `Updated ${c.entity_id?.replace("_", " ")}`}`;
  return `${changeLabel(c)}: ${show(c.before)} → ${show(c.after)}`;
}

export default function ChangeHistory() {
  const [rows, setRows] = useState<ChangeRow[]>([]);
  const [more, setMore] = useState(false);
  const [actions, setActions] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((beforeId?: number) => fetchChanges(beforeId).then(({ changes }) => {
    setRows((r) => (beforeId ? [...r, ...changes] : changes));
    setMore(changes.length === 50);
  }).catch((e) => setError(String(e.message))), []);
  useEffect(() => { void load(); }, [load]);

  const undo = (id: number) => undoChange(id).then(() => load()).catch((e) => setError(String(e.message)));
  const shown = rows.filter((c) => actions || c.entity !== "action");

  return (
    <section aria-label="Changes" className="agent-history">
      <label className="agent-history-toggle">
        <input type="checkbox" checked={actions} onChange={(e) => setActions(e.target.checked)} /> Also show actions (queued jobs, refreshes…)
      </label>
      {error && <div role="alert" className="alert">{error}</div>}
      {shown.length === 0 && !error && <p className="view-sub">No changes yet.</p>}
      <ul>
        {shown.map((c) => (
          <li key={c.id} className={c.undone_at ? "undone" : undefined}>
            <span className="agent-history-who">{WHO[c.actor]}</span>
            <span className="agent-history-what">{c.undo_of ? "Undid: " : ""}{describe(c)}</span>
            <time dateTime={c.at}>{new Date(c.at).toLocaleString()}</time>
            {c.undoable && !c.undone_at ? <button className="linkish" onClick={() => void undo(c.id)}>Undo</button>
              : c.undone_at ? <span className="agent-chip-done">Undone</span> : <span />}
          </li>
        ))}
      </ul>
      {more && <button className="btn btn-sm" onClick={() => void load(rows.at(-1)?.id)}>Older</button>}
    </section>
  );
}
