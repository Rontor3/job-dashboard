// Memory → History: every change to your data, by you or the agent, newest first, with Undo where it applies.
import { useCallback, useEffect, useState } from "react";
import { fetchChanges, undoChange, type ChangeRow } from "./client.ts";
import { show } from "./Thread.tsx";

const WHO = { agent: "Agent", ui: "You" } as const;

function what(c: ChangeRow): string {
  if (c.entity === "action") return `${c.field} ${c.entity_id}`;
  if (c.entity === "secret") return `${c.entity_id} set`;
  if (c.entity === "file") return `${c.entity_id} ${c.field === "upload" ? "uploaded" : "updated"}`;
  return `${c.entity} ${c.entity_id ?? ""} ${c.field ?? ""}: ${show(c.before)} → ${show(c.after)}`;
}

export default function ChangeHistory() {
  const [rows, setRows] = useState<ChangeRow[]>([]);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((beforeId?: number) => fetchChanges(beforeId).then(({ changes }) => {
    setRows((r) => (beforeId ? [...r, ...changes] : changes));
    setMore(changes.length === 50);
  }).catch((e) => setError(String(e.message))), []);
  useEffect(() => { void load(); }, [load]);

  const undo = (id: number) => undoChange(id).then(() => load()).catch((e) => setError(String(e.message)));

  return (
    <section aria-label="History" className="agent-history">
      {error && <div role="alert" className="alert">{error}</div>}
      {rows.length === 0 && !error && <p className="view-sub">No changes yet.</p>}
      <ul>
        {rows.map((c) => (
          <li key={c.id} className={c.undone_at ? "undone" : undefined}>
            <span className="agent-history-who">{WHO[c.actor]}</span>
            <span className="agent-history-what">{c.undo_of ? `Undo of #${c.undo_of}: ` : ""}{what(c)}</span>
            <time dateTime={c.at}>{new Date(c.at).toLocaleString()}</time>
            {c.undoable && !c.undone_at && <button className="linkish" onClick={() => void undo(c.id)}>Undo</button>}
            {c.undone_at && <span className="agent-chip-done">Undone</span>}
          </li>
        ))}
      </ul>
      {more && <button className="btn" onClick={() => void load(rows.at(-1)?.id)}>Older</button>}
    </section>
  );
}
