import React, { useCallback, useEffect, useState } from "react";
import { fetchJobQuestions, replyQuestion } from "../api.js";

const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };

// Open questions for one application: ones the agent couldn't answer, or
// drafted below the confidence threshold. Replying teaches memory and the
// question leaves this list (it then lives in the Answers tab).
export default function QuestionsPanel({ jobId, onChanged }) {
  const [qs, setQs] = useState(null);
  const [text, setText] = useState({});
  const [err, setErr] = useState(null);

  const load = useCallback(() => {
    fetchJobQuestions(jobId).then(setQs).catch(() => setQs([]));
  }, [jobId]);
  useEffect(() => { load(); }, [load]);

  const reply = (q) => {
    const answer = (text[q.id] ?? q.answer ?? "").trim();
    if (!answer) return;
    replyQuestion(jobId, q.id, answer)
      .then(() => { setErr(null); load(); if (onChanged) onChanged(); })
      .catch((e) => setErr(String(e)));
  };

  if (qs === null) return null;
  if (qs.length === 0) return <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>No open questions.</div>;
  return (
    <div data-testid={`questions-${jobId}`}>
      <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 6 }}>
        Needs your answer ({qs.length})
      </div>
      {err && <div role="alert" style={{ color: "var(--dupe-ink)", fontSize: 12 }}>{err}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {qs.map((q) => (
          <div key={q.id} style={{ background: "var(--warm-tint)", borderRadius: 10, padding: "8px 12px" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--warm-ink)" }}>{q.label}</div>
            {q.source === "judgment" && (
              <div style={{ fontSize: 11, color: "var(--ink-soft)", margin: "2px 0 6px" }}>
                Draft confidence: {q.confidence == null ? "unknown" : `${q.confidence}/100`}
                {q.basis ? ` — ${q.basis}` : ""}
                {q.unsupported_claims && q.unsupported_claims.length > 0 &&
                  ` · not found in context: ${q.unsupported_claims.join(", ")}`}
              </div>
            )}
            {q.context_json && q.context_json.prompt && (
              <details style={{ marginBottom: 6 }}>
                <summary style={{ fontSize: 11, color: "var(--ink-soft)", cursor: "pointer" }}>Context used</summary>
                <pre style={{ margin: "4px 0 0", fontSize: 10, maxHeight: 160, overflowY: "auto", whiteSpace: "pre-wrap",
                              background: "var(--canvas)", borderRadius: 6, padding: "6px 8px", color: "var(--ink-soft)" }}>
                  {q.context_json.prompt}
                </pre>
              </details>
            )}
            <textarea aria-label={`Answer for ${q.label}`} rows={2} style={INPUT}
                      value={text[q.id] ?? q.answer ?? ""} placeholder="Your answer"
                      onChange={(e) => setText({ ...text, [q.id]: e.target.value })} />
            <button onClick={() => reply(q)}
                    style={{ marginTop: 6, border: "none", cursor: "pointer", fontSize: 12, padding: "5px 12px",
                             borderRadius: "var(--radius-pill)", background: "var(--green)", color: "#fff" }}>
              Save to memory
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
