import React, { useEffect, useState } from "react";
import { fetchJob, saveApplyDetails } from "../api.js";

// Per-application facts the agent can't know. Forms that ask about referrals,
// relatives or past contact get "No" unless something is set here for this job.
const FLAGS = [
  ["relatives", "Relative or close friend works here"],
  ["applied_before", "Applied here before"],
  ["interviewed_before", "Interviewed here before"],
  ["worked_before", "Worked here before"],
];
const EMPTY = { referrer: "", relatives: false, applied_before: false, interviewed_before: false, worked_before: false };

export default function ApplyDetails({ jobId, onApply }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchJob(jobId)
      .then((j) => { if (!cancelled) setD({ ...EMPTY, ...(j.apply_details || {}) }); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [jobId]);

  if (error) return <div role="alert" className="skip-reasons">{error}</div>;
  if (!d) return <div className="skip-reasons">Loading…</div>;

  const set = (patch) => { setD({ ...d, ...patch }); setSaved(false); };
  const save = () => saveApplyDetails(jobId, d).then(() => setSaved(true));
  const fail = (e) => setError(String(e));

  return (
    <div className="skip-reasons" role="group" aria-label="Details for this application" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <span>Anything specific to this application? Left blank, the agent answers No.</span>
      <input className="ask-input" style={{ fontSize: 14, padding: "8px 12px" }} placeholder="Referred by (employee's name)"
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
