import React, { useCallback, useEffect, useState } from "react";
import { useOptionalAgent } from "../agent/AgentProvider.tsx";
import {
  addManyToQueue, agentLink, fetchAgentSettings, fetchJob, fetchJobs, fetchPreferences, forgetPreference, saveAgentSettings, sendJobFeedback,
} from "../api.js";
import ApplyDetails from "./ApplyDetails.jsx";

// Jobs ranked by fit + what your clicks taught. Every row asks for one decision: Apply (= more like this) or
// Skip with a one-tap reason (= less of exactly that). The learned strip shows what changed, and any chip can be
// removed if the agent learned the wrong thing. Tick as many as you like (or "Select strong fits") and apply to all
// of them at once: the apply agent fills every form, and only what it can't answer comes back to the Inbox.

const score = (j) => Math.round(j.llm_score ?? (j.embed_score || 0) * 100);
const DONE = ["applied", "interviewing", "offer", "rejected"];

function Learned({ prefs, onForget }) {
  if (!prefs) return null;
  const chips = [
    ...prefs.likes.map((x) => ({ ...x, cls: "chip-up", mark: "↑" })),
    ...prefs.dislikes.map((x) => ({ ...x, cls: "chip-down", mark: "↓" })),
    ...prefs.blocked_companies.map((c) => ({ feature: `company:${c}`, label: c, cls: "chip-down", mark: "✕" })),
  ];
  if (!chips.length) return <p className="learned">Apply or skip a few jobs. The ranking learns from every click.</p>;
  return (
    <div className="learned" aria-label="What the agent learned">
      <span>Learned:</span>
      {chips.map((c) => (
        <span key={c.feature} className={`chip ${c.cls}`}>
          {c.mark} {c.label}
          <button className="chip-x" aria-label={`Forget ${c.label}`} onClick={() => onForget(c.feature)}>×</button>
        </span>
      ))}
    </div>
  );
}

// Boards that need a login are fetched through the agent's own Chrome; each is opt-in.
const SITES = [["linkedin", "LinkedIn"], ["naukri", "Naukri"], ["indeed", "Indeed"], ["wellfound", "Wellfound"],
               ["instahyre", "Instahyre"], ["iimjobs", "iimjobs"], ["ycstartups", "YC startups"]];

function Sources() {
  const [s, setS] = useState(null);
  useEffect(() => { fetchAgentSettings().then(setS).catch(() => {}); }, []);
  if (!s) return null;
  const on = SITES.filter(([k]) => s[`browser_${k}_enabled`]).length;
  const toggle = (k) => {
    const key = `browser_${k}_enabled`;
    saveAgentSettings({ [key]: !s[key] }).then(() => setS({ ...s, [key]: !s[key] })).catch(() => {});
  };
  return (
    <details className="sources" data-agent="setting:browser_sources">
      <summary>Sources · {on ? `${on} logged-in board${on > 1 ? "s" : ""} on` : "public boards only"}</summary>
      <div className="chips" style={{ marginTop: 10 }}>
        {SITES.map(([k, label]) => (
          <button key={k} className="chip" aria-pressed={!!s[`browser_${k}_enabled`]} onClick={() => toggle(k)}>{label}</button>
        ))}
      </div>
      <p className="hint">Turned-on boards are fetched on Refresh through the agent's own Chrome. Log in to each once in that window.</p>
    </details>
  );
}

function Why({ id }) {
  const [d, setD] = useState(null);
  useEffect(() => { fetchJob(id).then(setD).catch(() => setD({})); }, [id]);
  if (!d) return null;
  return (
    <div className="job-why">
      {d.strengths?.length > 0 && <div><b>Fits:</b> {d.strengths.slice(0, 3).join(", ")}</div>}
      {d.gaps?.length > 0 && <div><b>Gaps:</b> {d.gaps.slice(0, 3).join(", ")}</div>}
      <div className="job-links">
        {d.job_url && <a href={d.job_url} onClick={agentLink(d.job_url)}>Open posting</a>}
      </div>
    </div>
  );
}

function JobRow({ job, reasons, onApply, onSkip, onOpen, queued, checked, onCheck }) {
  const [open, setOpen] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [details, setDetails] = useState(false);
  const pref = job.pref || 0;
  const done = DONE.includes(job.status);
  return (
    <li className={checked ? "job job-checked" : "job"} data-agent={`job:${job.id}`}>
      <div className="job-main">
        {!done && !queued ? (
          <input type="checkbox" className="job-check" checked={!!checked} onChange={() => onCheck(job.id)}
            aria-label={`Select ${job.title} at ${job.company}`} />
        ) : <span className="job-check" aria-hidden="true" />}
        <button className="job-text" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <div className="job-title">{job.title}</div>
          <div className="job-meta">{[job.company, job.location].filter(Boolean).join(" · ")}</div>
        </button>
        <div className="fit" data-band={score(job) >= 70 ? "high" : score(job) >= 50 ? "mid" : "low"}
          title="Fit score (adjusted by what you've taught it)">
          {score(job)}
          {Math.abs(pref) >= 1 && <small className={pref > 0 ? "up" : "down"}>{pref > 0 ? "↑" : "↓"} you</small>}
        </div>
        <div className="job-actions">
          {queued ? <span className="btn btn-sm btn-quiet">{queued}</span>
            : done ? <span className="btn btn-sm btn-quiet">{job.status}</span>
            : <button className="btn btn-sm btn-primary" onClick={() => onApply(job.id)}>Apply</button>}
          {!done && !queued && <button className="btn btn-sm" aria-expanded={details} onClick={() => setDetails((o) => !o)}>Details</button>}
          {!done && !queued && <button className="btn btn-sm" aria-expanded={skipping} onClick={() => setSkipping((s) => !s)}>Skip</button>}
        </div>
      </div>
      {details && !done && !queued && <ApplyDetails jobId={job.id} onApply={onApply} />}
      {skipping && (
        <div className="skip-reasons" role="group" aria-label="Why skip?">
          <span>Why?</span>
          {reasons.map((r) => (
            <button key={r.key} className="chip" onClick={() => onSkip(job.id, r.key)}>{r.label}</button>
          ))}
        </div>
      )}
      {open && (
        <>
          <Why id={job.id} />
          <button className="linkish" style={{ fontSize: 13, marginTop: 6 }} onClick={() => onOpen(job.id)}>
            Résumé, cover letter & run history
          </button>
        </>
      )}
    </li>
  );
}

function queuedLabel(queue, id) {
  const waiting = (queue?.items || []).filter((i) => i.state === "queued" || i.state === "running");
  const k = waiting.findIndex((i) => i.job_id === id);
  if (k < 0) return null;
  return waiting[k].state === "running" ? "Applying…" : `Queued #${k + 1}`;
}

const selectable = (j, queue) => !DONE.includes(j.status) && !queuedLabel(queue, j.id);

function BulkBar({ ids, onDone, onClear }) {
  const agent = useOptionalAgent();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const apply = () => {
    setBusy(true);
    addManyToQueue(ids).then((r) => { onDone(r); setBusy(false); })
      .catch((e) => { setError(String(e.message || e)); setBusy(false); });
  };
  const review = () => agent.start(
    `Have the critic and the advocate review jobs ${ids.join(", ")} against my target job. Strike the weak ones, `
    + "tell me why in a word or two each, and propose applying to the rest.");
  return (
    <div className="bulk-bar" role="region" aria-label="Selected jobs">
      <span className="bulk-count">{ids.length} selected</span>
      {error && <span role="alert" className="bulk-error">{error}</span>}
      <span className="spacer" />
      <button className="btn btn-quiet btn-sm" onClick={onClear}>Clear</button>
      {agent && <button className="btn btn-sm" onClick={review}>Review with the agents</button>}
      <button className="btn btn-primary" disabled={busy} onClick={apply}>
        {busy ? "Queueing…" : `Apply to ${ids.length}`}
      </button>
    </div>
  );
}

export default function JobsView({ queue, onApply, onOpen, refreshTick, focusIds, onClearFocus, onQueued }) {
  const [jobs, setJobs] = useState(null);
  const [selected, setSelected] = useState(() => new Set(focusIds || []));
  const [note, setNote] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [q, setQ] = useState("");
  const [india, setIndia] = useState(true);
  const [error, setError] = useState(null);

  const focus = focusIds?.length ? focusIds.join(",") : null;
  useEffect(() => { setSelected(new Set(focusIds || [])); }, [focus]);
  const load = useCallback(() => {
    const params = focus ? { sort: "learned", ids: focus, limit: 200 } : { sort: "learned", q, india, limit: 60 };
    Promise.all([fetchJobs(params), fetchPreferences()])
      .then(([feed, p]) => { setJobs(feed.jobs); setPrefs(p); setError(null); })
      .catch((e) => setError(String(e)));
  }, [q, india, focus]);
  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t); }, [load, q, refreshTick]);

  const toggle = (id) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const open = (jobs || []).filter((j) => selectable(j, queue));
  const strong = open.filter((j) => score(j) >= 70);
  const ids = (jobs || []).filter((j) => selected.has(j.id) && selectable(j, queue)).map((j) => j.id);
  const queued = (r) => {
    setSelected(new Set());
    setNote(`Queued ${r.queued.length} job${r.queued.length === 1 ? "" : "s"}${r.skipped.length ? ` (${r.skipped.length} skipped: already applied or gone)` : ""}. `
      + "The agent fills them one after another; anything it can't answer lands in your Inbox.");
    onQueued?.(r);
  };

  const skip = (id, reason) => {
    setJobs((js) => js.filter((j) => j.id !== id));
    sendJobFeedback(id, "skip", [reason]).then(() => load()).catch((e) => setError(String(e)));
  };
  const forget = (feature) => forgetPreference(feature).then(load).catch((e) => setError(String(e)));

  return (
    <section aria-label="Jobs">
      <h1 className="view-title">Jobs</h1>
      <p className="view-sub">Tick everything worth a shot and apply to all of it at once. Each choice reshapes this list.</p>
      {focus ? (
        <div className="focus-banner" role="status">
          <span>Showing {focusIds.length} job{focusIds.length === 1 ? "" : "s"} from the Inbox</span>
          <button className="linkish" onClick={onClearFocus}>Show all jobs</button>
        </div>
      ) : <>
        <Learned prefs={prefs} onForget={forget} />
        <Sources />
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input className="search" aria-label="Search jobs" placeholder="Search roles or companies"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="chip" aria-pressed={india} onClick={() => setIndia((v) => !v)}
            style={{ marginBottom: 14, whiteSpace: "nowrap" }}>India only</button>
        </div>
      </>}
      {open.length > 0 && (
        <div className="select-bar">
          <button className="linkish" disabled={!strong.length} onClick={() => setSelected(new Set(strong.map((j) => j.id)))}>
            Select strong fits ({strong.length})
          </button>
          <button className="linkish" onClick={() => setSelected(new Set(open.map((j) => j.id)))}>Select all {open.length}</button>
          {ids.length > 0 && <button className="linkish" onClick={() => setSelected(new Set())}>Select none</button>}
        </div>
      )}
      {note && <div className="note-ok" role="status">{note}</div>}
      {error && <div role="alert" className="alert">{error}</div>}
      {jobs && !jobs.length && (
        <div className="empty"><h2>No jobs here yet</h2><p>Use Refresh to pull new postings from the boards.</p></div>
      )}
      {jobs?.length > 0 && (
        <ul className="jobs">
          {jobs.map((j) => (
            <JobRow key={j.id} job={j} reasons={prefs?.skip_reasons || []} queued={queuedLabel(queue, j.id)}
              onApply={onApply} onSkip={skip} onOpen={onOpen} checked={selected.has(j.id)} onCheck={toggle} />
          ))}
        </ul>
      )}
      {ids.length > 0 && <BulkBar ids={ids} onDone={queued} onClear={() => setSelected(new Set())} />}
    </section>
  );
}
