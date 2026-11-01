import React, { useCallback, useEffect, useState } from "react";
import { fetchJobQuestions, replyQuestion } from "../api.js";
import EntryPicker from "./EntryPicker.jsx";

// About THIS company ("why do you want to join us") -> stays with the application.
// Everything else defaults to the Answers tab so it is answered from there next time.
const COMPANY_Q = /why\s+(this\s+)?(company|role|join|apply|us\b|our|do you want|are you interested)|motivat|what.{0,20}attract|interest\s+in\s+(this|the|our)\s+(role|position|company|job)|tell\s+us\s+why|what\s+interests\s+you/i;
// A best guess matched to one of your saved answers: confirming links this wording to it, so the next form asking it
// the same way is answered without you (not "Add to Answers", which made a second entry and asked again next time).
const linked = (q) => q.source === "qbank_likely" && !!q.retrieved_qkey;
const defaultMode = (q) => (linked(q) ? "wording" : COMPANY_Q.test(q.label || "") ? "once" : "new");

const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };

// A choice question (radio / select on the form) shows its options; the agent's pick, matched loosely, is preselected.
const optionsOf = (q) => (Array.isArray(q.options_json) ? q.options_json.filter((o) => String(o).trim()) : []);
function AnswerInput({ q, value, onChange }) {
  const opts = optionsOf(q);
  if (!opts.length) {
    return <textarea aria-label={`Answer for ${q.label}`} rows={2} style={INPUT} value={value} placeholder="Your answer"
                     onChange={(e) => onChange(e.target.value)} />;
  }
  const chosen = opts.find((o) => o.toLowerCase() === String(value).trim().toLowerCase()) || "";
  if (opts.length > 8) {
    return (
      <select aria-label={`Answer for ${q.label}`} style={INPUT} value={chosen} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  return (
    <div role="radiogroup" aria-label={`Answer for ${q.label}`} style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", fontSize: 12, margin: "4px 0" }}>
      {opts.map((o) => (
        <label key={o} style={{ color: "var(--ink)" }}>
          <input type="radio" name={`ans-${q.id}`} checked={chosen === o} onChange={() => onChange(o)} /> {o}
        </label>
      ))}
    </div>
  );
}

// Open questions for one application: ones the agent couldn't answer, or
// drafted below the confidence threshold. Replying teaches memory and the
// question leaves this list (it then lives in the Answers tab).
export default function QuestionsPanel({ jobId, onChanged }) {
  const [qs, setQs] = useState(null);
  const [text, setText] = useState({});
  const [mode, setMode] = useState({});
  const [pick, setPick] = useState({});
  const [err, setErr] = useState(null);

  const load = useCallback(() => {
    fetchJobQuestions(jobId).then(setQs).catch(() => setQs([]));
  }, [jobId]);
  useEffect(() => { load(); }, [load]);

  const reply = (q) => {
    const answer = (text[q.id] ?? q.answer ?? "").trim();
    const m = mode[q.id] || defaultMode(q);
    const entry = pick[q.id] ?? (linked(q) ? q.retrieved_qkey : null);
    if (!answer || (m === "wording" && !entry)) return;
    replyQuestion(jobId, q.id, answer, m, m === "wording" ? entry : null)
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
            {q.source === "qbank_likely" && (
              <div style={{ fontSize: 11, color: "var(--ink-soft)", margin: "2px 0 6px" }}>
                Filled with a best guess from your questionnaire (“{q.retrieved_qkey}”, score {q.retrieval_score}) — check it.
              </div>
            )}
            {linked(q) && !mode[q.id] && (
              <div style={{ fontSize: 11, color: "var(--ink-soft)", margin: "2px 0 6px" }}>
                Confirm to link this wording to your saved answer “{q.retrieved_qkey}” — next time it is filled without asking.
              </div>
            )}
            {q.asked_in > 1 && (
              <div style={{ fontSize: 11, color: "var(--warm-ink)" }}>Asked in {q.asked_in} applications — worth saving to the questionnaire.</div>
            )}
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
            <AnswerInput q={q} value={text[q.id] ?? q.answer ?? ""} onChange={(v) => setText({ ...text, [q.id]: v })} />
            <div role="radiogroup" aria-label={`Save ${q.label} as`} style={{ display: "flex", gap: 10, fontSize: 11, margin: "6px 0" }}>
              {[["new", "Add to Answers"], ["once", "Just this application"], ["wording", "Another wording of…"]].map(([v, t]) => (
                <label key={v}><input type="radio" name={`mode-${q.id}`} checked={(mode[q.id] || defaultMode(q)) === v}
                                      onChange={() => setMode({ ...mode, [q.id]: v })} /> {t}</label>
              ))}
            </div>
            {mode[q.id] === "wording" && (
              <EntryPicker id={`pick-${q.id}`} label={`Questionnaire entry for ${q.label}`}
                           onChange={(eid) => setPick({ ...pick, [q.id]: eid })} />
            )}
            <button onClick={() => reply(q)}
                    style={{ marginTop: 6, border: "none", cursor: "pointer", fontSize: 12, padding: "5px 12px",
                             borderRadius: "var(--radius-pill)", background: "var(--green)", color: "#fff" }}>
              {(mode[q.id] || defaultMode(q)) === "wording" && !mode[q.id] ? "Confirm" : "Save answer"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
