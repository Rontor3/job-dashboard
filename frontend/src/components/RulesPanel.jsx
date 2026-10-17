import React, { useCallback, useEffect, useState } from "react";
import { fetchLessons, updateLesson } from "../api.js";

// Memory → Rules: everything your insights taught. Rules (how to read a kind of question, what an essay should draw
// on) apply to later runs and can be edited or turned off; links, facts and defaults are filed in your Answers and
// listed here as history, with the value they replaced. Nothing is ever deleted.

const LEVER = { trust: "Trusted", fact: "Fact", lookup: "Other wording", policy: "Default", derive: "Worked out",
  shape: "Format", identify: "Field meaning", scope: "Essay material", guide: "Writing" };
const SCOPE = { question: "this question", similar: "same kind of question", long: "every essay", short: "every short field" };

function Rule({ l, onChange }) {
  const [text, setText] = useState(null);
  const save = (patch) => updateLesson(l.id, patch).then(onChange);
  const isRule = l.status === "active" || l.status === "off" || l.status === "superseded";
  return (
    <li className="mem-card" style={{ padding: "12px 14px", opacity: l.status === "active" || l.status === "filed" ? 1 : 0.6 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className="chip" style={{ padding: "2px 8px", fontSize: 11 }}>{LEVER[l.lever] || l.lever}</span>
        {isRule && <span style={{ fontSize: 12, color: "var(--ink-soft)" }}>applies to {SCOPE[l.applies_to] || l.applies_to}{l.max_words ? ` · max ${l.max_words} words` : ""}</span>}
        {l.status !== "active" && l.status !== "filed" && <span style={{ fontSize: 12, fontWeight: 600 }}>{l.status}</span>}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--ink-faint)" }}>
          #{l.id}{isRule ? ` · used ${l.hits}×` : ""} · {new Date(l.created_at).toLocaleDateString()}
        </span>
      </div>
      {text !== null ? (
        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
          <textarea aria-label={`Edit rule ${l.id}`} rows={2} value={text} onChange={(e) => setText(e.target.value)}
                    style={{ flex: 1, font: "inherit", fontSize: 13, padding: 6, borderRadius: 8 }} />
          <button className="btn btn-sm btn-primary" onClick={() => save({ rule: text }).then(() => setText(null))}>Save</button>
        </div>
      ) : (
        <p style={{ margin: "6px 0 2px", fontSize: 14 }}>{l.rule || l.concept}</p>
      )}
      {l.why && <p style={{ margin: 0, fontSize: 12, color: "var(--ink-soft)" }}>Why: {l.why}</p>}
      <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--ink-faint)" }}>
        {l.filed_in && l.filed_in !== "rule" ? `Filed as ${l.filed_in}` : null}
        {l.before?.answer != null ? ` · replaced “${l.before.answer}”` : l.before?.value != null ? ` · replaced “${l.before.value}”` : ""}
        {l.notes?.length ? ` · your note: “${l.notes[l.notes.length - 1]}”` : ""}
      </p>
      {(l.status === "active" || l.status === "off") && (
        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <button className="linkish" onClick={() => setText(l.rule || "")}>Edit</button>
          <button className="linkish" onClick={() => save({ status: l.status === "active" ? "off" : "active" })}>
            {l.status === "active" ? "Turn off" : "Turn on"}
          </button>
          <select aria-label={`Applies to, rule ${l.id}`} value={l.applies_to} onChange={(e) => save({ applies_to: e.target.value })}
                  style={{ fontSize: 12 }}>
            {Object.entries(SCOPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      )}
    </li>
  );
}

export default function RulesPanel() {
  const [all, setAll] = useState(null);
  const [showOld, setShowOld] = useState(false);
  const [error, setError] = useState(null);
  const load = useCallback(() => fetchLessons().then((d) => { setAll(d.lessons || []); setError(null); })
    .catch((e) => setError(String(e))), []);
  useEffect(() => { load(); }, [load]);
  if (error) return <div role="alert" className="alert">{error}</div>;
  if (!all) return null;
  const rules = all.filter((l) => l.status === "active" || l.status === "off");
  const filed = all.filter((l) => l.status === "filed");
  const old = all.filter((l) => l.status === "superseded");
  if (!all.length) {
    return <p className="view-sub">Nothing yet. In a job's last run, use “Tell it what's wrong” beside any answer; what it learns shows up here.</p>;
  }
  return (
    <section aria-label="Rules">
      <h2 className="section-title">Rules ({rules.length})</h2>
      <p className="view-sub">How to read a kind of question, or what an essay should draw on. Applied on every later run.</p>
      <ul className="jobs">{rules.map((l) => <Rule key={l.id} l={l} onChange={load} />)}</ul>
      {filed.length > 0 && <>
        <h2 className="section-title" style={{ marginTop: 24 }}>Filed in your Answers ({filed.length})</h2>
        <p className="view-sub">Facts, defaults and other wordings, saved where the agent looks first.</p>
        <ul className="jobs">{filed.map((l) => <Rule key={l.id} l={l} onChange={load} />)}</ul>
      </>}
      {old.length > 0 && (
        <button className="linkish" style={{ marginTop: 16 }} onClick={() => setShowOld((v) => !v)}>
          {showOld ? "Hide" : "Show"} {old.length} replaced rule{old.length === 1 ? "" : "s"}
        </button>
      )}
      {showOld && <ul className="jobs">{old.map((l) => <Rule key={l.id} l={l} onChange={load} />)}</ul>}
    </section>
  );
}
