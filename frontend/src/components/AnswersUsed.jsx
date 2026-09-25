import React, { useCallback, useEffect, useState } from "react";
import { fetchAnswersUsed, reviewAnswer } from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 11, padding: "3px 10px", borderRadius: "var(--radius-pill)" };

// What the agent filled for this application. Mark each right or wrong; a
// wrong one takes the correct answer and replaces it in memory.
export default function AnswersUsed({ jobId }) {
  const [rows, setRows] = useState(null);
  const [fixing, setFixing] = useState(null);       // {id, answer}
  const load = useCallback(() => { fetchAnswersUsed(jobId).then(setRows).catch(() => setRows([])); }, [jobId]);
  useEffect(() => { load(); }, [load]);
  if (!rows || rows.length === 0) return null;
  const send = (id, verdict, answer) => reviewAnswer(id, verdict, answer).then(() => { setFixing(null); load(); });
  return (
    <details data-testid={`used-${jobId}`}>
      <summary style={{ fontSize: 12, color: "var(--ink-soft)", cursor: "pointer" }}>Answers filled ({rows.length})</summary>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
        {rows.map((r) => (
          <div key={r.id} style={{ background: "var(--canvas)", borderRadius: 8, padding: "6px 10px", fontSize: 12 }}>
            <div style={{ color: "var(--ink)" }}>{r.label}</div>
            <div style={{ color: "var(--ink-soft)" }}>
              {r.answer} <em>({r.source})</em>
              {r.retrieval_kind && r.retrieval_kind !== "none" && r.retrieved_qkey &&
                <span style={{ color: "var(--ink-faint)" }}> · from “{r.retrieved_qkey}” ({r.retrieval_score})</span>}
            </div>
            {fixing && fixing.id === r.id ? (
              <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                <input aria-label={`Correct answer for ${r.label}`} value={fixing.answer} autoFocus
                       onChange={(e) => setFixing({ id: r.id, answer: e.target.value })}
                       style={{ flex: 1, fontSize: 12, padding: "4px 8px", border: "0.5px solid var(--hairline)", borderRadius: 6 }} />
                <button style={{ ...BTN, background: "var(--green)", color: "#fff" }}
                        onClick={() => send(r.id, "wrong", fixing.answer)}>Save fix</button>
              </div>
            ) : r.outcome ? (
              <span style={{ fontSize: 11, fontWeight: 600, color: r.outcome === "edited" ? "var(--dupe-ink)" : "var(--green)" }}>
                {r.outcome === "edited" ? "marked wrong" : "marked correct"}
              </span>
            ) : (
              <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                <button aria-label={`Correct: ${r.label}`} style={{ ...BTN, background: "var(--green-tint)", color: "var(--green)" }}
                        onClick={() => send(r.id, "correct")}>✓ Correct</button>
                <button aria-label={`Wrong: ${r.label}`} style={{ ...BTN, background: "var(--dupe-bg)", color: "var(--dupe-ink)" }}
                        onClick={() => setFixing({ id: r.id, answer: "" })}>✗ Wrong</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}
