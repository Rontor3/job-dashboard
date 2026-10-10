import React, { useCallback, useEffect, useState } from "react";
import { useOptionalAgent } from "../agent/AgentProvider.tsx";
import {
  addManyToQueue, fetchAgentSettings, fetchCompanyDetails, fetchJobs, fetchPreferences, forgetPreference, saveAgentSettings,
  sendJobFeedback,
} from "../api.js";
import JobGroups, { DONE, score } from "./JobGroups.jsx";

// Jobs ranked by fit + what your clicks taught, grouped by company (JobGroups.jsx). Every row asks for one decision:
// Apply (= more like this) or Skip with a one-tap reason (= less of exactly that). The learned strip shows what
// changed, and any chip can be removed if the agent learned the wrong thing. Tick as many as you like (a whole
// company, or "Select strong fits") and apply to all of them at once; only what the agent can't answer comes back.


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

function queuedLabel(queue, id) {
  const waiting = (queue?.items || []).filter((i) => i.state === "queued" || i.state === "running");
  const k = waiting.findIndex((i) => i.job_id === id);
  if (k < 0) return null;
  return waiting[k].state === "running" ? "Applying…" : `Queued #${k + 1}`;
}

const PAGE = 60;
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
  const [strongOnly, setStrongOnly] = useState(false);
  const [grouped, setGrouped] = useState(true);
  const [limit, setLimit] = useState(PAGE);
  const [total, setTotal] = useState(0);
  const [companies, setCompanies] = useState({});
  const [error, setError] = useState(null);

  const focus = focusIds?.length ? focusIds.join(",") : null;
  useEffect(() => { setSelected(new Set(focusIds || [])); }, [focus]);
  const load = useCallback(() => {
    const params = focus ? { sort: "learned", ids: focus, limit: 200 } : { sort: "learned", q, india, limit };
    Promise.all([fetchJobs(params), fetchPreferences(), fetchCompanyDetails().catch(() => ({ companies: {} }))])
      .then(([feed, p, c]) => { setJobs(feed.jobs); setTotal(feed.total ?? feed.jobs.length); setPrefs(p); setCompanies(c?.companies || {}); setError(null); })
      .catch((e) => setError(String(e)));
  }, [q, india, focus, limit]);
  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t); }, [load, q, refreshTick]);

  const toggle = (id) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const shown = (jobs || []).filter((j) => !strongOnly || score(j) >= 70);
  const open = shown.filter((j) => selectable(j, queue));
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
  const pick = (list, on) => setSelected((s) => {
    const n = new Set(s);
    list.forEach((id) => (on ? n.add(id) : n.delete(id)));
    return n;
  });
  const rowProps = (j) => ({ reasons: prefs?.skip_reasons || [], queued: queuedLabel(queue, j.id), onApply, onSkip: skip, onOpen,
    checked: selected.has(j.id), onCheck: toggle });
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
        <div className="jobs-tools">
          <input className="search" aria-label="Search jobs" placeholder="Search roles or companies"
            value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
          <button className="chip" aria-pressed={india} onClick={() => setIndia((v) => !v)}>India only</button>
          <button className="chip" aria-pressed={strongOnly} onClick={() => setStrongOnly((v) => !v)}>Strong fits only</button>
          <button className="chip" aria-pressed={grouped} onClick={() => setGrouped((v) => !v)}>By company</button>
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
      {shown.length > 0 && (
        <JobGroups jobs={shown} grouped={grouped && !focus} companyDetails={companies}
          onDetails={(key, details) => setCompanies((c) => ({ ...c, [key]: { ...(c[key] || {}), details } }))}
          selectable={(j) => selectable(j, queue)} selected={selected} onSelect={pick} rowProps={rowProps} />
      )}
      {!focus && jobs && total > jobs.length && (
        <div className="jobs-more">
          <span>Showing {jobs.length} of {total}</span>
          <button className="btn btn-sm" onClick={() => setLimit((n) => n + PAGE)}>Show {Math.min(PAGE, total - jobs.length)} more</button>
        </div>
      )}
      {ids.length > 0 && <BulkBar ids={ids} onDone={queued} onClear={() => setSelected(new Set())} />}
    </section>
  );
}
