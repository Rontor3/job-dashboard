import React, { useEffect, useState } from "react";
import { agentLink, fetchJob } from "../api.js";
import ApplyDetails from "./ApplyDetails.jsx";

// The Jobs list, one group per company (in rank order of its best opening): the header ticks every open role
// there and holds what's true for all of them (referrer, applied before…); each row is one line with the fit, Apply
// and Skip. Big groups show their best three until opened.

export const score = (j) => Math.round(j.llm_score ?? (j.embed_score || 0) * 100);
export const DONE = ["applied", "interviewing", "offer", "rejected"];
const FOLD = 3;

const ago = (iso) => {
  const d = iso && (Date.now() - new Date(iso).getTime()) / 864e5;
  if (!d || d < 0 || Number.isNaN(d)) return null;
  return d < 1 ? "today" : d < 2 ? "yesterday" : d < 30 ? `${Math.floor(d)}d ago` : `${Math.floor(d / 30)}mo ago`;
};
const companyKey = (c) => (c || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");

export function groupByCompany(jobs) {
  const groups = new Map();
  for (const j of jobs) {
    const k = companyKey(j.company) || `job-${j.id}`;
    if (!groups.has(k)) groups.set(k, { key: k, company: j.company || "Unknown company", jobs: [] });
    groups.get(k).jobs.push(j);
  }
  return [...groups.values()];
}

const FLAG_TEXT = { relatives: "relative works here", applied_before: "applied before", interviewed_before: "interviewed before",
  worked_before: "worked here before" };
function summary(d) {
  if (!d) return null;
  const bits = [d.referrer && `referred by ${d.referrer}`, ...Object.keys(FLAG_TEXT).filter((k) => d[k]).map((k) => FLAG_TEXT[k])];
  return bits.filter(Boolean).join(" · ") || null;
}

function Why({ id }) {
  const [d, setD] = useState(null);
  useEffect(() => { fetchJob(id).then(setD).catch(() => setD({})); }, [id]);
  if (!d) return null;
  return (
    <div className="job-why">
      {d.strengths?.length > 0 && <div><b>Fits:</b> {d.strengths.slice(0, 3).join(", ")}</div>}
      {d.gaps?.length > 0 && <div><b>Gaps:</b> {d.gaps.slice(0, 3).join(", ")}</div>}
      <div className="job-links">{d.job_url && <a href={d.job_url} onClick={agentLink(d.job_url)}>Open posting</a>}</div>
    </div>
  );
}

function JobRow({ job, reasons, onApply, onSkip, onOpen, queued, checked, onCheck, showCompany, aside }) {
  const [open, setOpen] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const pref = job.pref || 0;
  const done = DONE.includes(job.status);
  const s = score(job);
  const when = ago(job.posted_date);
  return (
    <li className={checked ? "job job-checked" : "job"} data-agent={`job:${job.id}`}>
      <div className="job-main">
        {!done && !queued ? (
          <input type="checkbox" className="job-check" checked={!!checked} onChange={() => onCheck(job.id)}
            aria-label={`Select ${job.title} at ${job.company}`} />
        ) : <span className="job-check" aria-hidden="true" />}
        <button className="job-text" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className="job-title">{job.title}</span>
          <span className="job-meta">{[showCompany && job.company, job.location, when].filter(Boolean).join(" · ")}</span>
        </button>
        {aside}
        <div className="fit" data-band={s >= 70 ? "high" : s >= 50 ? "mid" : "low"} title="Fit score (adjusted by what you've taught it)">
          {s}
          {Math.abs(pref) >= 1 && <small className={pref > 0 ? "up" : "down"}>{pref > 0 ? "↑" : "↓"} you</small>}
        </div>
        <div className="job-actions">
          {queued ? <span className="btn btn-sm btn-quiet">{queued}</span>
            : done ? <span className="btn btn-sm btn-quiet">{job.status}</span>
            : <button className="btn btn-sm btn-primary" onClick={() => onApply(job.id)}>Apply</button>}
          {!done && !queued && <button className="btn btn-sm" aria-expanded={skipping} onClick={() => setSkipping((v) => !v)}>Skip</button>}
        </div>
      </div>
      {skipping && (
        <div className="skip-reasons" role="group" aria-label="Why skip?">
          <span>Why?</span>
          {reasons.map((r) => <button key={r.key} className="chip" onClick={() => onSkip(job.id, r.key)}>{r.label}</button>)}
        </div>
      )}
      {open && (
        <>
          <Why id={job.id} />
          <button className="linkish job-more" onClick={() => onOpen(job.id)}>Résumé, cover letter & run history</button>
        </>
      )}
    </li>
  );
}

function CompanyGroup({ group, details, onDetails, selectable, selected, onSelect, rowProps }) {
  const [all, setAll] = useState(false);
  const [editing, setEditing] = useState(false);
  const open = group.jobs.filter(selectable);
  const ticked = open.filter((j) => selected.has(j.id)).length;
  const shown = all ? group.jobs : group.jobs.slice(0, FOLD);
  const best = Math.max(...group.jobs.map(score));
  const said = summary(details);
  const facts = (
    <button className={said ? "company-facts company-facts-set" : "company-facts"} aria-expanded={editing}
      aria-label={said || `Referral, applied before… at ${group.company}`} onClick={() => setEditing((v) => !v)}>
      {said || "Referral, applied before…"}
    </button>
  );
  const editor = editing && (
    <ApplyDetails company={group.company} initial={details} onSaved={(d) => { onDetails(group.key, d); setEditing(false); }} />
  );
  if (group.jobs.length === 1) {                 // one opening: one line, the company's details beside it
    const [j] = group.jobs;
    return (
      <li className="company company-solo" aria-label={group.company}>
        <ul className="jobs"><JobRow job={j} showCompany aside={facts} {...rowProps(j)} /></ul>
        {editor}
      </li>
    );
  }
  return (
    <li className="company" aria-label={group.company}>
      <div className="company-head">
        {open.length > 0 ? (
          <input type="checkbox" className="job-check" checked={ticked === open.length}
            ref={(el) => { if (el) el.indeterminate = ticked > 0 && ticked < open.length; }}
            onChange={() => onSelect(open.map((j) => j.id), ticked < open.length)}
            aria-label={`Select every open role at ${group.company}`} />
        ) : <span className="job-check" aria-hidden="true" />}
        <div className="company-name">
          <strong>{group.company}</strong>
          <span>{group.jobs.length} opening{group.jobs.length > 1 ? "s" : ""} · best fit {best}</span>
        </div>
        {facts}
      </div>
      {editor}
      <ul className="jobs">
        {shown.map((j) => <JobRow key={j.id} job={j} {...rowProps(j)} />)}
      </ul>
      {group.jobs.length > FOLD && (
        <button className="linkish company-fold" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show ${group.jobs.length - FOLD} more at ${group.company}`}
        </button>
      )}
    </li>
  );
}

export default function JobGroups({ jobs, grouped, companyDetails, onDetails, selectable, selected, onSelect, rowProps }) {
  if (!grouped) {
    return <ul className="jobs">{jobs.map((j) => <JobRow key={j.id} job={j} showCompany {...rowProps(j)} />)}</ul>;
  }
  return (
    <ul className="companies">
      {groupByCompany(jobs).map((g) => (
        <CompanyGroup key={g.key} group={g} details={companyDetails[g.key]?.details} onDetails={onDetails}
          selectable={selectable} selected={selected} onSelect={onSelect} rowProps={rowProps} />
      ))}
    </ul>
  );
}
