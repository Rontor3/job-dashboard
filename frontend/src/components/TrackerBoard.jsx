import React, { useCallback, useEffect, useState } from "react";
import { fetchTracker, patchStatus } from "../api.js";

const COLS = [
  { key: "saved", label: "Saved" },
  { key: "applied", label: "Applied" },
  { key: "interviewing", label: "Interviewing" },
  { key: "offer", label: "Offer" },
];
const STAGE_OPTS = ["saved", "applied", "interviewing", "offer", "rejected"];
const PILL = { fontSize: 10, padding: "2px 8px", borderRadius: "var(--radius-pill)", background: "#F1EBE0", color: "var(--ink-soft)" };
const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: 8, marginBottom: 8 };

export default function TrackerBoard({ onSelect }) {
  const [board, setBoard] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => { fetchTracker().then(setBoard).catch((e) => setErr(String(e))); }, []);
  useEffect(() => { load(); }, [load]);

  const move = (id, status) => patchStatus(id, status).then(load);

  if (err) return <div role="alert" style={{ color: "var(--dupe-ink)", padding: 16 }}>{err}</div>;
  if (!board) return <div style={{ padding: 24, color: "var(--ink-soft)" }}>Loading board…</div>;

  const Card = (j) => (
    <div key={j.id} draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(j.id))}
      onClick={() => onSelect(j.id)} style={{ ...CARD, cursor: "grab" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>{j.title}</div>
      <div style={{ fontSize: 10, color: "var(--ink-soft)" }}>{j.company}</div>
      {j.industry && <span style={{ ...PILL, display: "inline-block", marginTop: 4 }}>{j.industry}</span>}
      <select data-testid={`stage-${j.id}`} value={j.status}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => { const val = e.target.value; e.stopPropagation();
          move(j.id, val === "__remove__" ? null : val); }}
        style={{ display: "block", marginTop: 6, fontSize: 10, width: "100%" }}>
        {STAGE_OPTS.map((s) => <option key={s} value={s}>{s}</option>)}
        <option value="__remove__">Remove from board</option>
      </select>
    </div>
  );

  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: "flex", gap: 10 }}>
        {COLS.map((c) => (
          <div key={c.key} data-testid={`col-${c.key}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const id = Number(e.dataTransfer.getData("text/plain")); if (id) move(id, c.key); }}
            style={{ flex: 1, background: "var(--ring-track)", borderRadius: 12, padding: 8, minHeight: 120 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--green)", marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
              <span>{c.label}</span><span>{(board[c.key] || []).length}</span>
            </div>
            {(board[c.key] || []).length === 0
              ? <div style={{ fontSize: 10, color: "var(--ink-faint)" }}>—</div>
              : board[c.key].map(Card)}
          </div>
        ))}
      </div>
      <details style={{ marginTop: 12 }}>
        <summary style={{ fontSize: 12, color: "var(--ink-soft)", cursor: "pointer" }}>
          Archived ({(board.archived || []).length})
        </summary>
        <div style={{ marginTop: 8 }}>{(board.archived || []).map(Card)}</div>
      </details>
    </div>
  );
}
