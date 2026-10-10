import React, { useEffect, useState } from "react";
import { fetchJob, saveApplyDetails, saveCompanyDetails } from "../api.js";

// Facts the agent can't know about you and an employer. Forms that ask about referrals, relatives or past contact
// get "No" unless something is set. With `company`, they're set once for every opening there (the Jobs tab's
// company header); with `jobId`, for one application only, on top of the company's.
const FLAGS = [
  ["relatives", "Relative or close friend works here"],
  ["applied_before", "Applied here before"],
  ["interviewed_before", "Interviewed here before"],
  ["worked_before", "Worked here before"],
];
const EMPTY = { referrer: "", relatives: false, applied_before: false, interviewed_before: false, worked_before: false };

export default function ApplyDetails({ jobId, company, initial, onApply, onSaved }) {
  const [d, setD] = useState(company ? { ...EMPTY, ...(initial || {}) } : null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (company) return undefined;
    let cancelled = false;
    fetchJob(jobId)
      .then((j) => { if (!cancelled) setD({ ...EMPTY, ...(j.apply_details || {}) }); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [jobId, company]);

  if (error) return <div role="alert" className="skip-reasons">{error}</div>;
  if (!d) return <div className="skip-reasons">Loading…</div>;

  const set = (patch) => { setD({ ...d, ...patch }); setSaved(false); };
  const save = () => (company ? saveCompanyDetails(company, d) : saveApplyDetails(jobId, d))
    .then((r) => { setSaved(true); onSaved?.(company ? r.details : d); });
  const fail = (e) => setError(String(e));

  return (
    <div className="skip-reasons apply-details" role="group"
      aria-label={company ? `Details for every opening at ${company}` : "Details for this application"}>
      <span>{company ? `True for every opening at ${company}? Left blank, the agent answers No.`
        : "Anything specific to this application? Left blank, the agent answers No."}</span>
      <input className="ask-input" placeholder="Referred by (employee's name)"
             aria-label="Referred by" maxLength={120} value={d.referrer} onChange={(e) => set({ referrer: e.target.value })} />
      <div className="chips">
        {FLAGS.map(([key, label]) => (
          <button key={key} className="chip" aria-pressed={d[key]} onClick={() => set({ [key]: !d[key] })}>{label}</button>
        ))}
      </div>
      <div className="job-actions">
        {onApply && <button className="btn btn-sm btn-primary" onClick={() => save().then(() => onApply(jobId)).catch(fail)}>Save & apply</button>}
        <button className="btn btn-sm" onClick={() => save().catch(fail)}>{saved ? "Saved" : "Save"}</button>
      </div>
    </div>
  );
}
