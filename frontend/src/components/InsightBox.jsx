import React, { useEffect, useState } from "react";
import { editFilledAnswer, launchApplyAgent, lessonReach, rewriteAnswer, saveLesson } from "../api.js";

// Beside one answer of a run: say what's wrong in your own words; the agent works out the CAUSE (a missing fact,
// other wording, a default, a comparison with the job, the wrong material…), rewrites the answer the way the next
// run would, and shows what it will learn and how far that reaches before anything is saved.

const CAUSE = {
  trust: "It was right — only held back as unsure",
  fact: "A fact about you was missing or wrong",
  lookup: "It's already in your Answers under other words",
  policy: "A standing default for this kind of question",
  derive: "It has to be worked out (e.g. the job vs. you)",
  shape: "Right fact, wrong part or format",
  identify: "The label didn't say what the field asks",
  scope: "The essay used the wrong material",
  guide: "How this kind of answer should be written",
};
const RULE_LEVERS = ["derive", "shape", "identify", "scope", "guide"];
const SCOPES = [["question", "Only this question"], ["similar", "Questions about the same thing"],
                ["long", "Every essay answer"], ["short", "Every short field"]];

function learns(p) {
  if (!p) return "";
  if (p.lever === "trust" || p.lever === "lookup") return p.entry_id ? `This wording will point to your saved answer “${p.entry_id}”.` : "Saved as a new answer for this wording.";
  if (p.lever === "fact" || p.lever === "policy") return p.entry_id ? `Your saved answer “${p.entry_id}” becomes “${p.value}” (the old value is kept in the history).` : `Saved as a new answer: “${p.value}”.`;
  if (p.lever === "derive" && p.derived) return `Saved as a worked-out fact “${p.derived.key}”, recomputed for every job.`;
  return `Kept as a rule (below) for the questions it applies to${p.max_words ? `, with a hard limit of ${p.max_words} words` : ""}.`;
}

const box = { marginTop: 6, padding: "10px 12px", borderRadius: 10, background: "var(--card)", border: "1px solid var(--hairline)",
  display: "flex", flexDirection: "column", gap: 8 };
const input = { width: "100%", boxSizing: "border-box", font: "inherit", fontSize: 13, padding: "8px 10px", borderRadius: 8,
  border: "1px solid var(--hairline)", background: "var(--canvas)", color: "var(--ink)", resize: "vertical" };

export default function InsightBox({ q, jobId, onDone }) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState([]);
  const [draft, setDraft] = useState("");
  const [res, setRes] = useState(null);
  const [answer, setAnswer] = useState("");
  const [rule, setRule] = useState("");
  const [scope, setScope] = useState("question");
  const [remember, setRemember] = useState(true);
  const [reach, setReach] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [done, setDone] = useState(null);

  const isRule = res && RULE_LEVERS.includes(res.proposal.lever);
  useEffect(() => {
    if (!isRule || !remember) { setReach(null); return; }
    lessonReach({ concept: res.proposal.concept, applies_to: scope, label: q.label, kind: q.kind || "text" })
      .then(setReach).catch(() => setReach(null));
  }, [isRule, remember, scope, res, q.label, q.kind]);

  if (!open) {
    return <div><button type="button" className="linkish" style={{ fontSize: 12, marginTop: 4 }} onClick={() => setOpen(true)}
                   aria-label={`Tell it what's wrong: ${q.label}`}>Tell it what's wrong</button></div>;
  }
  if (done) {
    return (
      <div style={box} role="status">
        <span style={{ fontSize: 13 }}>Saved. {done}</span>
        <div style={{ display: "flex", gap: 8 }}>
          {jobId && <button type="button" className="btn btn-sm" onClick={() => launchApplyAgent(jobId).catch(() => {})}>Re-run this application</button>}
          <button type="button" className="btn btn-sm btn-quiet" onClick={() => { setOpen(false); setDone(null); onDone?.(); }}>Close</button>
        </div>
      </div>
    );
  }

  const ask = () => {
    const all = [...notes, draft.trim()].filter(Boolean);
    if (!all.length) return;
    setBusy(true); setErr(null);
    rewriteAnswer(q.id, all)
      .then((r) => {
        setNotes(all); setDraft(""); setRes(r); setAnswer(r.answer ?? "");
        setRule(r.proposal.rule || ""); setScope(r.proposal.applies_to || "question");
      })
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setBusy(false));
  };
  const accept = async () => {
    setBusy(true); setErr(null);
    try {
      if (answer.trim()) await editFilledAnswer(q.id, answer.trim(), "once");
      let msg = "Answer saved for this application.";
      if (remember) {
        const f = await saveLesson({ ...res.proposal, rule, applies_to: scope }, answer.trim() || null);
        msg = `Learned: ${f.filed_in}.`;
      }
      setDone(msg);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  return (
    <div style={box} aria-label={`Insight for ${q.label}`}>
      {notes.length > 0 && <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--ink-soft)" }}>{notes.map((n, i) => <li key={i}>{n}</li>)}</ol>}
      <textarea aria-label="What's wrong" rows={2} style={input} value={draft} placeholder={res ? "Not quite? Add more…" :
        "e.g. “don't use my projects here”, “it's in my answers as total experience”, “compare the job's city with mine”"}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); }} />
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn btn-sm btn-primary" disabled={busy || (!draft.trim() && !notes.length)} onClick={ask}>
          {busy && !res ? "Rewriting…" : res ? "Try again" : "Rewrite"}
        </button>
        <button type="button" className="btn btn-sm btn-quiet" onClick={() => { setOpen(false); setRes(null); setNotes([]); }}>Discard</button>
      </div>
      {err && <div role="alert" className="alert" style={{ marginTop: 0 }}>{err}</div>}
      {res && (
        <>
          <div style={{ fontSize: 12 }}>
            <b>Cause:</b> {CAUSE[res.proposal.lever]}{res.directive.why ? ` — ${res.directive.why}` : ""}
          </div>
          <label style={{ fontSize: 12, fontWeight: 600 }}>New answer
            <textarea aria-label="New answer" rows={Math.min(14, Math.max(2, Math.ceil((answer || "").length / 80)))} style={{ ...input, marginTop: 4 }}
                      value={answer} placeholder="It couldn't work one out — type it, or add more above"
                      onChange={(e) => setAnswer(e.target.value)} />
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Learn from this
          </label>
          {remember && <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>{learns(res.proposal)}</div>}
          {remember && isRule && (
            <>
              <label style={{ fontSize: 12, fontWeight: 600 }}>The rule
                <textarea aria-label="Rule" rows={2} style={{ ...input, marginTop: 4 }} value={rule} onChange={(e) => setRule(e.target.value)} />
              </label>
              <label style={{ fontSize: 12 }}>Applies to{" "}
                <select aria-label="Applies to" value={scope} onChange={(e) => setScope(e.target.value)}>
                  {SCOPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </label>
              {reach && (
                <details style={{ fontSize: 12, color: "var(--ink-soft)" }}>
                  <summary>Would have applied to {reach.count} past question{reach.count === 1 ? "" : "s"}</summary>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{reach.examples.map((x) => <li key={x.label}>{x.label}</li>)}</ul>
                </details>
              )}
            </>
          )}
          <details style={{ fontSize: 11, color: "var(--ink-faint)" }}>
            <summary>How it got there</summary>
            <pre style={{ whiteSpace: "pre-wrap", margin: "4px 0 0" }}>{(res.trace || []).join("\n")}</pre>
          </details>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="btn btn-sm btn-primary" disabled={busy || (!answer.trim() && !remember)} onClick={accept}>Accept</button>
          </div>
        </>
      )}
    </div>
  );
}
