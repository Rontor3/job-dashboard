import React, { useCallback, useEffect, useMemo, useState } from "react";
import RetrievalPanel from "./RetrievalPanel.jsx";
import {
  fetchAnswers, saveAnswer, deleteAnswer, fetchAgentSettings, saveAgentSettings, saveApplicationProfile,
} from "../api.js";

// Memory → Answers: the question bank, one topic at a time. A rail on the left lists the topics with how many are
// answered; "To fill" collects every unanswered entry so the next thing to do is always one click away. A row
// shows the question and its saved answer; click it to edit, see the other wordings forms use, or remove it.
export const TOPICS = [
  ["work_auth", "Work authorization"], ["compensation", "Compensation"], ["availability", "Availability"],
  ["location", "Location"], ["experience", "Experience & education"], ["background", "Background"],
  ["preferences", "Preferences"], ["demographics", "Demographics (voluntary)"], ["misc", "Other"],
  ["story", "Your story"],
];
const TO_FILL = "_to_fill";
export const unanswered = (a) => a.needs_input && a.value == null;
const topicOf = (a) => a.topic || "misc";

function shownValue(a) {
  if (a.profile_ref && a.atype === "bool") return a.value == null ? null : /^(true|1|yes)$/i.test(a.value) ? "Yes" : "No";
  return a.profile_ref ? a.value : a.answer;
}

// How bold the apply agent is, in words: each preset is a pair of thresholds (questionnaire match, drafted answer).
const PRESETS = [
  { key: "careful", label: "Careful", qbank: 93, conf: 75,
    text: "Fills only what it's sure of and asks you about the rest. More questions in your Inbox, almost no wrong answers." },
  { key: "balanced", label: "Balanced", qbank: 87, conf: 60,
    text: "Fills what it's confident about and flags close calls for you to check before anything is sent." },
  { key: "bold", label: "Bold", qbank: 75, conf: 45,
    text: "Fills nearly everything itself. Fewest questions for you; now and then an answer needs fixing." },
];

export function Thresholds() {
  const [s, setS] = useState(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { fetchAgentSettings().then(setS).catch(() => {}); }, []);
  if (!s) return null;
  const put = (v) => saveAgentSettings({
    answer_confidence_min: Number(v.answer_confidence_min), qbank_confident_min: Number(v.qbank_confident_min),
  }).then(() => { setSaved(true); setTimeout(() => setSaved(false), 1500); });
  const current = PRESETS.find((p) => Number(s.qbank_confident_min) === p.qbank && Number(s.answer_confidence_min) === p.conf);
  const choose = (p) => {
    const v = { ...s, qbank_confident_min: p.qbank, answer_confidence_min: p.conf };
    setS(v);
    put(v);
  };
  const row = (key, id, label, hint) => (
    <div className="mem-threshold">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="number" min="0" max="100" value={s[key]} onChange={(e) => setS({ ...s, [key]: e.target.value })} />
      <span>{hint}</span>
    </div>
  );
  return (
    <div className="mem-card tune" data-agent="setting:thresholds">
      <h3 className="tune-h">How much should the agent decide on its own?</h3>
      <p className="tune-sub">When a form asks something, the agent answers from what you've told it. This sets how sure it
        must be before it answers without checking with you. Nothing is ever submitted without your say.</p>
      <div className="tune-presets" role="radiogroup" aria-label="How bold the agent is">
        {PRESETS.map((p) => (
          <button key={p.key} type="button" role="radio" aria-checked={current?.key === p.key} className="tune-preset" onClick={() => choose(p)}>
            <strong>{p.label}{p.key === "balanced" && <small> · recommended</small>}</strong>
            <span>{p.text}</span>
          </button>
        ))}
      </div>
      <p className="tune-status" role="status">{saved ? "Saved." : current ? "" : "You've set your own numbers below."}</p>
      <details className="tune-advanced">
        <summary>Advanced: the exact numbers</summary>
        {row("qbank_confident_min", "qbank-min", "Minimum match score to fill from the questionnaire without flagging",
             "Below this, the best match is still filled but listed for you to check before submit.")}
        {row("answer_confidence_min", "conf-min", "Minimum confidence to fill a generated answer",
             "Below this (or unknown) a drafted answer is not filled.")}
        <div><button className="btn btn-primary btn-sm" onClick={() => put(s)} aria-label="Save thresholds">{saved ? "Saved" : "Save"}</button></div>
      </details>
    </div>
  );
}

function Editor({ a, onSave, onSaveProfile }) {
  const initial = shownValue(a) ?? "";
  const [draft, setDraft] = useState(initial);
  const label = `Answer for ${a.question}`;
  const input = a.topic === "story"
    ? <textarea aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} />
    : a.atype === "bool"
    ? <select aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)}>
        <option value="">—</option><option>Yes</option><option>No</option>
      </select>
    : <input aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && draft.trim() && draft.trim() !== initial) (a.profile_ref ? onSaveProfile : onSave)(a, draft.trim()); }} />;
  return (
    <div className="mem-edit">
      {input}
      <button className="btn btn-primary btn-sm" aria-label={`Save ${a.question}`}
        disabled={!draft.trim() || draft.trim() === initial}
        onClick={() => (a.profile_ref ? onSaveProfile : onSave)(a, draft.trim())}>Save</button>
    </div>
  );
}

function Row({ a, open, onToggle, onSave, onSaveProfile, onRemove }) {
  const value = shownValue(a);
  const wordings = a.wordings.filter((w) => w !== a.question);
  const story = a.topic === "story";
  const editing = open || (unanswered(a) && !story);              // unwritten essays stay one line until opened
  return (
    <li className={`mem-row${unanswered(a) ? " mem-open" : ""}`} data-testid={`entry-${a.id}`}
      data-agent={a.profile_ref ? `profile:${a.profile_ref}` : `qbank:${a.id}`}>
      <button className="mem-row-head" aria-expanded={open} onClick={onToggle}>
        <span className="mem-q">{a.question}</span>
        {!editing && <span className="mem-a">{value ?? (story ? "Not written yet: the agent drafts it from your projects" : "—")}</span>}
        <span className="mem-meta">
          {a.asked_in ? `asked ${a.asked_in}×` : ""}
          {!a.profile_ref && a.topic !== "story" && (a.approvals || 0) >= 3 && <span className="mem-auto" title="May submit without you"> ✓ auto</span>}
        </span>
      </button>
      {editing && <Editor key={value ?? ""} a={a} onSave={onSave} onSaveProfile={onSaveProfile} />}
      {a.rule_help && editing && <p className="mem-hint">{a.rule_help}</p>}
      {open && (
        <div className="mem-details">
          {a.profile_ref && <p className="mem-hint">From your profile ({a.profile_ref}): saving updates every question that uses it.</p>}
          {!a.profile_ref && a.topic !== "story" && (
            <p className="mem-hint" data-testid={`approvals-${a.id}`}>
              {(a.approvals || 0) >= 3 ? "✓ autonomous — may submit without you" : `approved ${a.approvals || 0} of 3 times`}
            </p>
          )}
          <p className="mem-hint">{a.asked_in ? `Asked in ${a.asked_in} application${a.asked_in === 1 ? "" : "s"}` : "Not asked yet"}
            {wordings.length > 0 && ` · also worded as: ${wordings.join(" · ")}`}</p>
          <button className="linkish" aria-label={`Remove ${a.question}`} onClick={() => onRemove(a)}>Remove</button>
        </div>
      )}
    </li>
  );
}

export default function AnswersTab({ only }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [topic, setTopic] = useState(null);
  const [open, setOpen] = useState(null);
  const [err, setErr] = useState(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ question: "", answer: "" });

  const load = useCallback(() => {
    fetchAnswers(q).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(String(e)));
  }, [q]);
  useEffect(() => { load(); }, [load]);

  const saveProfile = (a, v) => saveApplicationProfile({ [a.profile_ref]: a.atype === "bool" ? v === "Yes" : v })
    .then(load).catch((e) => setErr(String(e)));
  const save = (a, answer) => saveAnswer({ entry_id: a.id, answer }).then(load).catch((e) => setErr(String(e)));
  const remove = (a) => {
    if (window.confirm(`Remove "${a.question}" from the questionnaire?`)) deleteAnswer(a.id).then(load).catch((e) => setErr(String(e)));
  };
  const add = () => saveAnswer(draft).then(() => { setDraft({ question: "", answer: "" }); setAdding(false); load(); })
    .catch((e) => setErr(String(e)));

  const all = useMemo(() => (data?.answers ?? []).filter((a) => (only ? topicOf(a) === only : topicOf(a) !== "story")), [data, only]);
  const toFill = all.filter(unanswered);
  const topics = TOPICS.filter(([k]) => !only ? k !== "story" : k === only)
    .map(([k, title]) => ({ k, title, items: all.filter((a) => topicOf(a) === k) })).filter((t) => t.items.length);
  const current = only ?? topic ?? (toFill.length ? TO_FILL : topics[0]?.k);
  const searching = q.trim().length > 0;
  const shown = searching || only ? all : current === TO_FILL ? toFill : all.filter((a) => topicOf(a) === current);
  const groups = searching
    ? topics.map((t) => ({ ...t, items: t.items.filter((a) => shown.includes(a)) })).filter((t) => t.items.length)
    : [{ k: current, title: null, items: shown }];

  const rows = (items) => (
    <ul className="mem-list">
      {items.map((a) => <Row key={a.id} a={a} open={open === a.id} onToggle={() => setOpen(open === a.id ? null : a.id)}
        onSave={save} onSaveProfile={saveProfile} onRemove={remove} />)}
    </ul>
  );

  return (
    <div className={only ? "mem-answers mem-single" : "mem-answers"}>
      {!only && (
        <nav className="mem-rail" aria-label="Topics">
          <button aria-current={current === TO_FILL && !searching ? "true" : undefined} onClick={() => { setTopic(TO_FILL); setQ(""); }}>
            <span>To fill</span><span className={toFill.length ? "mem-count mem-count-warm" : "mem-count"}>{toFill.length}</span>
          </button>
          {topics.map((t) => (
            <button key={t.k} aria-current={current === t.k && !searching ? "true" : undefined} onClick={() => { setTopic(t.k); setQ(""); }}>
              <span>{t.title}</span>
              <span className="mem-count">{t.items.filter((a) => !unanswered(a)).length}/{t.items.length}</span>
            </button>
          ))}
        </nav>
      )}
      <div className="mem-pane">
        <div className="mem-toolbar">
          <input aria-label="Search questions" placeholder="Search every question and answer…" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn btn-sm" onClick={() => setAdding(!adding)}>+ Add question</button>
        </div>
        {err && <div role="alert" className="alert">{err}</div>}
        {adding && (
          <div className="mem-card mem-add">
            <input aria-label="New question" placeholder="Question, as the form words it" value={draft.question}
              onChange={(e) => setDraft({ ...draft, question: e.target.value })} />
            <input aria-label="New answer" placeholder="Answer" value={draft.answer}
              onChange={(e) => setDraft({ ...draft, answer: e.target.value })} />
            <div><button className="btn btn-primary btn-sm" onClick={add}>Save</button></div>
          </div>
        )}
        {data === null ? <p className="view-sub">Loading questionnaire…</p>
          : current === TO_FILL && !searching && !toFill.length ? <p className="view-sub">Nothing to fill. Every question has an answer.</p>
          : groups.map((g) => (
            <section key={g.k} aria-label={g.title ?? undefined}>
              {g.title && <h3 className="mem-group">{g.title}</h3>}
              {rows(g.items)}
            </section>
          ))}
        {searching && groups.length === 0 && <p className="view-sub">No question or answer matches “{q}”.</p>}
      </div>
    </div>
  );
}

export function Tuning() {
  return (
    <div className="mem-tuning">
      <Thresholds />
      <details className="tune-advanced mem-card">
        <summary>Advanced: how questions are matched to your answers</summary>
        <RetrievalPanel />
      </details>
    </div>
  );
}
