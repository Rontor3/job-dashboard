import React, { useCallback, useEffect, useState } from "react";
import RetrievalPanel from "./RetrievalPanel.jsx";
import {
  fetchAnswers, saveAnswer, deleteAnswer, fetchAnswerApps,
  fetchAgentSettings, saveAgentSettings, fetchIngredients,
} from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "5px 12px", borderRadius: "var(--radius-pill)" };
const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };
const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "10px 14px" };

function Trust({ a }) {
  if (!a.in_vault) return null;
  const label = a.autonomous ? "autonomous" : `${a.approved_count ?? 0}/3 approvals`;
  return (
    <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: "var(--radius-pill)",
                   background: a.autonomous ? "var(--green)" : "#F1EBE0", color: a.autonomous ? "#fff" : "var(--ink-soft)" }}>
      {label}
    </span>
  );
}

function AskedIn({ a }) {
  const [apps, setApps] = useState(null);
  if (!a.asked_in) return <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>not asked yet</span>;
  return (
    <details onToggle={(e) => { if (e.target.open && apps === null) fetchAnswerApps(a.qkey).then(setApps).catch(() => setApps([])); }}>
      <summary style={{ fontSize: 11, color: "var(--ink-soft)", cursor: "pointer" }}>
        asked in {a.asked_in} application{a.asked_in === 1 ? "" : "s"}
      </summary>
      <ul style={{ margin: "4px 0 0", paddingLeft: 16, fontSize: 11, color: "var(--ink-soft)" }}>
        {(apps || []).map((j) => <li key={j.job_id}>{j.title} · {j.company}</li>)}
      </ul>
    </details>
  );
}

function Threshold() {
  const [v, setV] = useState(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { fetchAgentSettings().then((s) => setV(s.answer_confidence_min)).catch(() => {}); }, []);
  if (v === null) return null;
  const save = () => saveAgentSettings(Number(v)).then(() => { setSaved(true); setTimeout(() => setSaved(false), 1500); });
  return (
    <div style={{ ...CARD, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
      <label htmlFor="conf-min" style={{ fontSize: 12, color: "var(--ink)" }}>
        Minimum confidence to fill a generated answer
      </label>
      <input id="conf-min" type="number" min="0" max="100" value={v} onChange={(e) => setV(e.target.value)}
             style={{ ...INPUT, width: 70 }} />
      <button onClick={save} aria-label="Save threshold" style={{ ...BTN, background: "var(--green)", color: "#fff" }}>{saved ? "Saved" : "Save"}</button>
      <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>
        Below this (or unknown) the answer is not filled — it appears under the job's Tracker row for you to answer.
      </span>
    </div>
  );
}

function Ingredients() {
  const [d, setD] = useState(null);
  useEffect(() => { fetchIngredients().then(setD).catch(() => {}); }, []);
  if (!d || !d.units.length) return null;
  return (
    <details style={{ marginTop: 16 }}>
      <summary style={{ fontSize: 12, color: "var(--ink-soft)", cursor: "pointer" }}>
        Ingredients ({d.units.length}) — read-only, edited in ingredients.json
      </summary>
      <ul style={{ margin: "6px 0 0", paddingLeft: 16, fontSize: 12, color: "var(--ink-soft)" }}>
        {d.units.map((u) => <li key={u.id}>{u.title}{u.org ? ` · ${u.org}` : ""} <em>({u.type})</em></li>)}
      </ul>
    </details>
  );
}

export default function AnswersTab() {
  const [answers, setAnswers] = useState(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState(null);
  const [edit, setEdit] = useState(null);       // {qkey, question, answer}
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ question: "", answer: "" });

  const load = useCallback(() => {
    fetchAnswers(q).then((a) => { setAnswers(a); setErr(null); }).catch((e) => setErr(String(e)));
  }, [q]);
  useEffect(() => { load(); }, [load]);

  const save = (body, done) => saveAnswer(body).then(() => { done(); load(); }).catch((e) => setErr(String(e)));
  const remove = (a) => {
    if (window.confirm(`Delete the answer to "${a.question}"?`)) deleteAnswer(a.qkey).then(load).catch((e) => setErr(String(e)));
  };

  return (
    <div style={{ marginTop: 14 }}>
      <Threshold />
      <RetrievalPanel />
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input aria-label="Search answers" placeholder="Search questions and answers…" value={q}
               onChange={(e) => setQ(e.target.value)} style={INPUT} />
        <button onClick={() => setAdding(!adding)} style={{ ...BTN, background: "var(--green)", color: "#fff", whiteSpace: "nowrap" }}>
          + Add answer
        </button>
      </div>
      {err && <div role="alert" style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{err}</div>}
      {adding && (
        <div style={{ ...CARD, display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
          <input aria-label="New question" placeholder="Question, as the form words it" value={draft.question}
                 onChange={(e) => setDraft({ ...draft, question: e.target.value })} style={INPUT} />
          <textarea aria-label="New answer" placeholder="Answer" value={draft.answer} rows={2}
                    onChange={(e) => setDraft({ ...draft, answer: e.target.value })} style={INPUT} />
          <div><button style={{ ...BTN, background: "var(--green)", color: "#fff" }}
                       onClick={() => save(draft, () => { setDraft({ question: "", answer: "" }); setAdding(false); })}>Save</button></div>
        </div>
      )}
      {answers === null ? <div style={{ color: "var(--ink-soft)", padding: 16 }}>Loading answers…</div>
        : answers.length === 0 ? <div style={{ color: "var(--ink-soft)", padding: "32px 0", textAlign: "center" }}>
            {q ? "No answers match." : "No saved answers yet — they appear as you answer questions the agent couldn't."}</div>
        : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {answers.map((a) => (
              <div key={a.qkey} data-testid={`answer-${a.qkey}`} style={CARD}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{a.question}</div>
                    {edit && edit.qkey === a.qkey ? (
                      <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
                        <textarea aria-label="Edit answer" rows={2} value={edit.answer} style={INPUT}
                                  onChange={(e) => setEdit({ ...edit, answer: e.target.value })} />
                        <div style={{ display: "flex", gap: 6 }}>
                          <button style={{ ...BTN, background: "var(--green)", color: "#fff" }}
                                  onClick={() => save({ question: a.question, answer: edit.answer, purpose: a.purpose }, () => setEdit(null))}>Save</button>
                          <button style={{ ...BTN, background: "var(--canvas)", color: "var(--ink-soft)" }} onClick={() => setEdit(null)}>Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 2, whiteSpace: "pre-wrap" }}>{a.answer}</div>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
                    <Trust a={a} />
                    <button style={{ ...BTN, background: "var(--canvas)", color: "var(--ink-soft)" }}
                            onClick={() => setEdit({ qkey: a.qkey, answer: a.answer || "" })}>Edit</button>
                    <button style={{ ...BTN, background: "var(--dupe-bg)", color: "var(--dupe-ink)" }} onClick={() => remove(a)}>Delete</button>
                  </div>
                </div>
                <div style={{ marginTop: 6 }}><AskedIn a={a} /></div>
              </div>
            ))}
          </div>
        )}
      <Ingredients />
    </div>
  );
}
