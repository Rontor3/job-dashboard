import React, { useEffect, useState } from "react";
import { fetchRetrievalStats, fetchRetrievalRecent } from "../api.js";

const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "10px 14px" };
const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);

function Stat({ label, value, hint, testid }) {
  return (
    <div style={{ ...CARD, flex: "1 1 130px" }} title={hint}>
      <div data-testid={testid} style={{ fontSize: 20, fontWeight: 600, color: "var(--green)" }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--ink-soft)" }}>{label}</div>
    </div>
  );
}

const TIER = { purpose: "same purpose", label_exact: "exact question", fts_fuzzy: "similar wording", semantic: "similar meaning", none: "no match" };

// How well is memory retrieval working: what it matches, what it answers, and
// how often the answer turned out wrong (from your reviews and agent submits).
export default function RetrievalPanel() {
  const [s, setS] = useState(null);
  const [recent, setRecent] = useState([]);
  useEffect(() => {
    fetchRetrievalStats().then(setS).catch(() => {});
    fetchRetrievalRecent().then(setRecent).catch(() => {});
  }, []);
  if (!s) return null;
  if (!s.total_fields) {
    return <div style={{ ...CARD, marginBottom: 12, fontSize: 12, color: "var(--ink-soft)" }}>
      Retrieval: no runs recorded yet. Stats appear after the agent fills an application.</div>;
  }
  const g = s.generation;
  return (
    <details open style={{ marginBottom: 14 }}>
      <summary style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)", cursor: "pointer", marginBottom: 8 }}>Retrieval</summary>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <Stat testid="stat-hit" label="fields memory found a match for" value={pct(s.hit_rate)} hint={`${s.retrieval_hits} of ${s.total_fields} fields`} />
        <Stat testid="stat-used" label="answered from memory" value={s.answered_by_memory} hint="a retrieved entry actually filled the field" />
        <Stat testid="stat-unused" label="matched but not used" value={s.retrieved_not_used} hint="e.g. a semantic match below the 3-approval autonomy bar" />
        <Stat testid="stat-wrong" label="wrong when reviewed" value={pct(s.reviewed.wrong_rate)}
              hint={`${s.reviewed.edited} wrong, ${s.reviewed.kept} correct`} />
      </div>
      <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 8 }}>
        Matched by: {Object.entries(s.by_tier).map(([k, n]) => `${TIER[k] || k} ${n}`).join(" · ") || "—"}
      </div>
      {s.top_wrong_entries.length > 0 && (
        <div style={{ ...CARD, marginBottom: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Entries most often wrong</div>
          {s.top_wrong_entries.map((w) => (
            <div key={w.qkey} style={{ fontSize: 12, color: "var(--ink-soft)" }}>
              “{w.qkey}” — wrong {w.edited}×, right {w.kept}×
            </div>
          ))}
        </div>
      )}
      {(g.kept.count > 0 || g.edited.count > 0) && (
        <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 8 }} data-testid="calibration">
          Generated answers — average confidence when right: {g.kept.avg_confidence ?? "—"} ({g.kept.count}) ·
          when wrong: {g.edited.avg_confidence ?? "—"} ({g.edited.count}). Set the threshold between them.
        </div>
      )}
      <div style={{ ...CARD }}>
        <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 6 }}>Recent</div>
        {recent.map((r) => (
          <div key={r.id} data-testid={`recent-${r.id}`} style={{ padding: "6px 0", borderTop: "0.5px solid var(--hairline)", fontSize: 12 }}>
            <div style={{ color: "var(--ink)" }}>{r.label}
              <span style={{ color: "var(--ink-faint)" }}> · {r.title} @ {r.company}</span></div>
            <div style={{ color: "var(--ink-soft)" }}>
              {r.retrieval_kind && r.retrieval_kind !== "none"
                ? <>matched “{r.retrieved_qkey}” ({TIER[r.retrieval_kind] || r.retrieval_kind}, score {r.retrieval_score})</>
                : "nothing retrieved"}
              {" → "}{r.status === "needs_answer" ? "not filled" : <>“{r.answer}” <em>({r.source})</em></>}
              {r.outcome && <strong style={{ color: r.outcome === "edited" ? "var(--dupe-ink)" : "var(--green)" }}> · {r.outcome === "edited" ? "wrong" : "correct"}</strong>}
            </div>
            {r.candidates_json && r.candidates_json.length > 0 && (
              <details><summary style={{ fontSize: 11, color: "var(--ink-faint)", cursor: "pointer" }}>considered {r.candidates_json.length}</summary>
                <ul style={{ margin: "2px 0 0", paddingLeft: 16, fontSize: 11, color: "var(--ink-soft)" }}>
                  {r.candidates_json.map((c, i) => (
                    <li key={i}>{c.tier}: “{c.qkey}” score {c.score} — {c.accepted ? "passed the gate" : "rejected by the gate"}</li>
                  ))}
                </ul></details>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}
