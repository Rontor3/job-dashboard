import React, { useCallback, useEffect, useState } from "react";
import RetrievalPanel from "./RetrievalPanel.jsx";
import {
  fetchAnswers, saveAnswer, deleteAnswer, fetchAgentSettings, saveAgentSettings, fetchIngredients,
} from "../api.js";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "5px 12px", borderRadius: "var(--radius-pill)" };
const INPUT = { fontSize: 12, padding: "6px 10px", border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--canvas)", color: "var(--ink)", width: "100%", boxSizing: "border-box" };
const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "10px 14px" };
const TOPICS = [
  ["work_auth", "Work authorization"], ["compensation", "Compensation"], ["availability", "Availability"],
  ["location", "Location"], ["experience", "Experience & education"], ["background", "Background"],
  ["demographics", "Demographics (voluntary)"], ["misc", "Other"],
];
const unanswered = (a) => a.needs_input && a.value == null;

function Thresholds() {
  const [s, setS] = useState(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { fetchAgentSettings().then(setS).catch(() => {}); }, []);
  if (!s) return null;
  const save = () => saveAgentSettings({
    answer_confidence_min: Number(s.answer_confidence_min), qbank_confident_min: Number(s.qbank_confident_min),
  }).then(() => { setSaved(true); setTimeout(() => setSaved(false), 1500); });
  const row = (key, id, label, hint) => (
    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
      <label htmlFor={id} style={{ fontSize: 12, color: "var(--ink)" }}>{label}</label>
      <input id={id} type="number" min="0" max="100" value={s[key]} style={{ ...INPUT, width: 70 }}
             onChange={(e) => setS({ ...s, [key]: e.target.value })} />
      <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>{hint}</span>
    </div>
  );
  return (
    <div style={{ ...CARD, display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
      {row("qbank_confident_min", "qbank-min", "Minimum match score to fill from the questionnaire without flagging",
           "Below this, the best match is still filled but listed for you to check before submit.")}
      {row("answer_confidence_min", "conf-min", "Minimum confidence to fill a generated answer",
           "Below this (or unknown) a drafted answer is not filled.")}
      <div><button onClick={save} aria-label="Save thresholds" style={{ ...BTN, background: "var(--green)", color: "#fff" }}>{saved ? "Saved" : "Save"}</button></div>
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

function Entry({ a, onSave, onRemove }) {
  const [draft, setDraft] = useState(a.answer ?? "");
  const input = a.atype === "bool"
    ? <select aria-label={`Answer for ${a.question}`} value={draft} onChange={(e) => setDraft(e.target.value)} style={{ ...INPUT, width: 120 }}>
        <option value="">—</option><option>Yes</option><option>No</option>
      </select>
    : <input aria-label={`Answer for ${a.question}`} value={draft} onChange={(e) => setDraft(e.target.value)} style={INPUT} />;
  return (
    <div data-testid={`entry-${a.id}`} style={{ ...CARD, borderColor: unanswered(a) ? "var(--warm-ink)" : "var(--hairline)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{a.question}</div>
        <button aria-label={`Remove ${a.question}`} onClick={() => onRemove(a)}
                style={{ ...BTN, background: "var(--dupe-bg)", color: "var(--dupe-ink)", flexShrink: 0 }}>Remove</button>
      </div>
      {a.profile_ref ? (
        <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 4 }}>
          <span>{a.value ?? "not set"}</span> <em>— from your profile ({a.profile_ref})</em>
        </div>
      ) : a.needs_input ? (
        <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
          {input}
          <button aria-label={`Save ${a.question}`} disabled={!draft.trim()} onClick={() => onSave(a, draft)}
                  style={{ ...BTN, background: "var(--green)", color: "#fff" }}>Save</button>
        </div>
      ) : null}
      {a.rule_help && <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 4 }}>{a.rule_help}</div>}
      <details style={{ marginTop: 4 }}>
        <summary style={{ fontSize: 11, color: "var(--ink-soft)", cursor: "pointer" }}>
          {a.asked_in ? `asked in ${a.asked_in} application${a.asked_in === 1 ? "" : "s"}` : "not asked yet"}
          {` · ${a.wordings.length} wording${a.wordings.length === 1 ? "" : "s"}`}
        </summary>
        <ul style={{ margin: "2px 0 0", paddingLeft: 16, fontSize: 11, color: "var(--ink-soft)" }}>
          {a.wordings.filter((w) => w !== a.question).map((w) => <li key={w}>{w}</li>)}
        </ul>
      </details>
    </div>
  );
}

export default function AnswersTab() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [err, setErr] = useState(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ question: "", answer: "" });

  const load = useCallback(() => {
    fetchAnswers(q).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(String(e)));
  }, [q]);
  useEffect(() => { load(); }, [load]);

  const save = (a, answer) => saveAnswer({ entry_id: a.id, answer }).then(load).catch((e) => setErr(String(e)));
  const remove = (a) => {
    if (window.confirm(`Remove "${a.question}" from the questionnaire?`)) deleteAnswer(a.id).then(load).catch((e) => setErr(String(e)));
  };
  const add = () => saveAnswer(draft).then(() => { setDraft({ question: "", answer: "" }); setAdding(false); load(); })
    .catch((e) => setErr(String(e)));

  const shown = data ? data.answers.filter((a) => !onlyOpen || unanswered(a)) : [];
  return (
    <div style={{ marginTop: 14 }}>
      <Thresholds />
      <RetrievalPanel />
      <div style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>Questionnaire</strong>
        {data && <span style={{ fontSize: 12, color: "var(--warm-ink)" }}>{data.unanswered} unanswered</span>}
        <label style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center" }}>
          <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} aria-label="Only unanswered" />
          Only unanswered
        </label>
        <button onClick={() => setAdding(!adding)} style={{ ...BTN, background: "var(--green)", color: "#fff", marginLeft: "auto" }}>+ Add question</button>
      </div>
      <input aria-label="Search questions" placeholder="Search questions and answers…" value={q}
             onChange={(e) => setQ(e.target.value)} style={{ ...INPUT, marginBottom: 10 }} />
      {err && <div role="alert" style={{ color: "var(--dupe-ink)", fontSize: 12, marginBottom: 8 }}>{err}</div>}
      {adding && (
        <div style={{ ...CARD, display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
          <input aria-label="New question" placeholder="Question, as the form words it" value={draft.question}
                 onChange={(e) => setDraft({ ...draft, question: e.target.value })} style={INPUT} />
          <input aria-label="New answer" placeholder="Answer" value={draft.answer}
                 onChange={(e) => setDraft({ ...draft, answer: e.target.value })} style={INPUT} />
          <div><button style={{ ...BTN, background: "var(--green)", color: "#fff" }} onClick={add}>Save</button></div>
        </div>
      )}
      {data === null ? <div style={{ color: "var(--ink-soft)", padding: 16 }}>Loading questionnaire…</div>
        : TOPICS.map(([key, title]) => {
          const items = shown.filter((a) => (a.topic || "misc") === key);
          if (!items.length) return null;
          return (
            <section key={key} style={{ marginBottom: 14 }}>
              <h3 style={{ fontSize: 13, color: "var(--ink-soft)", margin: "8px 0" }}>{title}</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {items.map((a) => <Entry key={a.id} a={a} onSave={save} onRemove={remove} />)}
              </div>
            </section>
          );
        })}
      <Ingredients />
    </div>
  );
}
