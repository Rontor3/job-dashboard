import React, { useCallback, useEffect, useState } from "react";
import { addAboutFact, fetchAboutMe, saveAboutMe } from "../api.js";
import { useOptionalAgent } from "../agent/AgentProvider.tsx";
import { describe } from "../agent/ChangeHistory.tsx";
import { fetchChanges, undoChange } from "../agent/client.ts";
import { MISSIONS } from "../agent/TeamRail.tsx";

// Memory → About you: what the agents have learned about you (data/agent/about-me.md), which every agent session
// reads. Facts are grouped by what they're for; fix or remove any of them, add your own, or have the agent
// interview you. Below, the latest things the agent saved anywhere (profile, answers, this page), each with Undo.

const HINTS = {
  Target: "The job you're after: role, level, where, pay floor",
  Preferences: "What you like in a role or company",
  Constraints: "Hard no's: places, company kinds, conditions",
  Background: "Context that doesn't fit the profile or résumé",
  "Working style": "How you want the agents to work with you",
  Other: "Anything else",
};

const bullet = /^\s*[-*] /;

/** The file without the bullet `fact` (first match). */
export function withoutFact(text, fact) {
  const lines = text.split("\n");
  const i = lines.findIndex((l) => bullet.test(l) && l.replace(bullet, "").trim() === fact);
  return i < 0 ? text : [...lines.slice(0, i), ...lines.slice(i + 1)].join("\n");
}

function Fact({ fact, onReword, onRemove }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fact);
  if (editing) {
    return (
      <li className="about-fact about-fact-edit">
        <input aria-label={`Reword ${fact}`} value={draft} autoFocus onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && draft.trim()) { onReword(fact, draft.trim()); setEditing(false); } if (e.key === "Escape") setEditing(false); }} />
        <button className="btn btn-sm btn-primary" disabled={!draft.trim()} onClick={() => { onReword(fact, draft.trim()); setEditing(false); }}>Save</button>
      </li>
    );
  }
  return (
    <li className="about-fact">
      <span>{fact}</span>
      <button className="linkish" aria-label={`Edit ${fact}`} onClick={() => setEditing(true)}>Edit</button>
      <button className="linkish" aria-label={`Remove ${fact}`} onClick={() => onRemove(fact)}>Remove</button>
    </li>
  );
}

function AddFact({ section, onAdd }) {
  const [draft, setDraft] = useState("");
  const add = () => { if (draft.trim().length > 1) { onAdd(section, draft.trim()); setDraft(""); } };
  return (
    <div className="about-add">
      <input aria-label={`Add to ${section}`} placeholder={HINTS[section] || "Add a fact"} value={draft}
        onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
      {draft.trim() && <button className="btn btn-sm" onClick={add}>Add</button>}
    </div>
  );
}

function RecentlyLearned({ tick }) {
  const [rows, setRows] = useState(null);
  // A run of the same change (the agent adding 8 ingredients) reads as one line, with Undo on the latest.
  const load = useCallback(() => fetchChanges().then(({ changes }) => {
    const out = [];
    for (const c of changes.filter((x) => x.actor === "agent" && x.entity !== "action")) {
      const last = out.at(-1);
      if (last && describe(last) === describe(c) && !c.undone_at === !last.undone_at) last.times += 1;
      else out.push({ ...c, times: 1 });
    }
    setRows(out.slice(0, 8));
  }).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load, tick]);
  if (!rows?.length) return null;
  return (
    <section className="mem-card about-recent" aria-label="Recently learned">
      <h3 className="mem-group">What the agent saved lately</h3>
      <ul>
        {rows.map((c) => (
          <li key={c.id} className={c.undone_at ? "undone" : undefined}>
            <span>{describe(c)}{c.times > 1 ? ` (${c.times}×)` : ""}</span>
            <time dateTime={c.at}>{new Date(c.at).toLocaleDateString()}</time>
            {c.undoable && !c.undone_at ? <button className="linkish" onClick={() => undoChange(c.id).then(load)}>Undo</button>
              : c.undone_at ? <span className="agent-chip-done">Undone</span> : <span />}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function AboutMe() {
  const agent = useOptionalAgent();
  const [about, setAbout] = useState(null);
  const [raw, setRaw] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  const load = useCallback(() => fetchAboutMe().then((a) => { setAbout(a); setError(null); }).catch((e) => setError(String(e.message || e))), []);
  useEffect(() => { load(); }, [load]);
  const done = (p) => p.then((a) => { setAbout(a); setTick((t) => t + 1); }).catch((e) => setError(String(e.message || e)));

  if (error) return <div role="alert" className="alert">{error}</div>;
  if (!about) return <p className="view-sub">Loading…</p>;
  const sections = [...about.known_sections, ...Object.keys(about.sections).filter((s) => !about.known_sections.includes(s))];
  const count = Object.values(about.sections).reduce((n, f) => n + f.length, 0);
  const interview = MISSIONS.find((m) => m.title === "Get to know me");

  return (
    <div className="about">
      <div className="about-intro">
        <p className="view-sub">
          {count ? `${count} thing${count === 1 ? "" : "s"} the agents know about you. Every agent session reads this page, so they don't ask twice.`
            : "The agents haven't learned anything about you yet. Tell them in chat, add facts here, or let one interview you."}
        </p>
        <div className="about-intro-actions">
          {agent && interview && <button className="btn btn-primary btn-sm" onClick={() => agent.start(interview.message)}>Have the agent interview me</button>}
          <button className="btn btn-sm" onClick={() => setRaw(raw === null ? about.text : null)}>{raw === null ? "Edit as text" : "Back to facts"}</button>
        </div>
      </div>
      {raw !== null ? (
        <div className="mem-card">
          <textarea className="about-raw" aria-label="About me, as text" rows={18} value={raw} onChange={(e) => setRaw(e.target.value)} />
          <div><button className="btn btn-primary btn-sm" onClick={() => done(saveAboutMe(raw)).then(() => setRaw(null))}>Save</button></div>
        </div>
      ) : (
        <div className="about-grid">
          {sections.map((s) => (
            <section key={s} className="mem-card about-section" data-agent={`about:${s}`} aria-label={s}>
              <h3 className="mem-group">{s}</h3>
              {(about.sections[s] || []).length > 0 && (
                <ul className="about-facts">
                  {about.sections[s].map((f) => (
                    <Fact key={f} fact={f} onReword={(old, next) => done(addAboutFact(s, next, old))}
                      onRemove={(old) => done(saveAboutMe(withoutFact(about.text, old)))} />
                  ))}
                </ul>
              )}
              {about.known_sections.includes(s) && <AddFact section={s} onAdd={(sec, fact) => done(addAboutFact(sec, fact))} />}
            </section>
          ))}
        </div>
      )}
      <RecentlyLearned tick={tick} />
    </div>
  );
}
