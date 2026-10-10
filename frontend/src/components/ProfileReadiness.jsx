import React, { useCallback, useEffect, useRef, useState } from "react";
import { autofillProfile, fetchReadiness } from "../api.js";

// How ready you are for application forms, like a dating app's "profile 80% complete": the share of what forms
// usually ask that the agents already know, with the must-haves called out. When your résumé is new (or never read),
// it's read into the gaps by itself first, so you're only asked what nobody can find.

function Ring({ percent }) {
  const r = 34, c = 2 * Math.PI * r;
  return (
    <svg className="ready-ring" viewBox="0 0 80 80" aria-hidden="true">
      <circle cx="40" cy="40" r={r} className="ready-track" />
      <circle cx="40" cy="40" r={r} className="ready-fill" strokeDasharray={c} strokeDashoffset={c * (1 - percent / 100)} />
      <text x="40" y="45" textAnchor="middle">{percent}%</text>
    </svg>
  );
}

export default function ProfileReadiness({ tick = 0, onChange }) {
  const [r, setR] = useState(null);
  const [reading, setReading] = useState(false);
  const [note, setNote] = useState(null);
  const auto = useRef(false);

  const fill = useCallback(() => {
    setReading(true);
    setNote(null);
    return autofillProfile().then((out) => {
      setR({ ...out.readiness, autofill_due: false });
      const n = out.filled?.length || 0;
      setNote(n ? `Filled ${n} from your ${out.sources.join(", ").toLowerCase()}: ${out.filled.map((f) => f.value).slice(0, 3).join(" · ")}${n > 3 ? "…" : ""}`
        : `Read your ${(out.sources || []).join(", ").toLowerCase() || "documents"}; nothing new in them.`);
      onChange?.();
    }).catch((e) => setNote(`Couldn't read your documents: ${e.message || e}`)).finally(() => setReading(false));
  }, [onChange]);

  useEffect(() => {
    fetchReadiness().then((d) => {
      setR(d);
      if (d?.autofill_due && !auto.current) { auto.current = true; fill(); }     // a new résumé: read it first
    }).catch(() => {});
  }, [tick, fill]);

  if (!r || typeof r.percent !== "number") return null;
  const must = r.required_missing || [];
  const situational = (r.optional_missing || []).filter((m) => m.why);       // only some of your jobs ask these
  return (
    <section className={`ready${r.ready ? " ready-ok" : ""}`} aria-label="Profile readiness">
      <Ring percent={r.percent} />
      <div className="ready-main">
        <h2 className="ready-title">
          {r.ready ? "You're good to go" : must.length ? `${must.length} must-have${must.length > 1 ? "s" : ""} missing` : "Almost there"}
        </h2>
        <p className="ready-sub">
          {reading ? "Reading your résumé and LinkedIn into your profile…"
            : note || (r.ready
              ? "The agents know what application forms ask. They'll only come back for something unusual."
              : `The agents know ${r.percent}% of what application forms usually ask.`)}
        </p>
        {must.length > 0 && !reading && (
          <div className="ready-chips">{must.slice(0, 8).map((m) => <span key={m.key} className="ready-chip">{m.label}</span>)}</div>
        )}
        {situational.length > 0 && !reading && (
          <div className="ready-chips" aria-label="Asked by some of your jobs">
            <span className="ready-for">For your jobs:</span>
            {situational.map((m) => <span key={m.key} className="ready-chip ready-chip-sit" title={m.why}>{m.label}</span>)}
          </div>
        )}
      </div>
      <button className="btn btn-sm" disabled={reading} onClick={fill}>{reading ? "Reading…" : "Fill from my résumé & LinkedIn"}</button>
    </section>
  );
}
