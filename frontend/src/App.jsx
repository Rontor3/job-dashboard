import React, { useCallback, useEffect, useState } from "react";
import { fetchJobs, fetchStats, fetchQueue, addToQueue, fetchInbox, fetchNotifications } from "./api.js";
import FilterBar from "./components/FilterBar.jsx";
import Feed from "./components/Feed.jsx";
import JobDetail from "./components/JobDetail.jsx";
import RefreshButton from "./components/RefreshButton.jsx";
import DuplicatesSection from "./components/DuplicatesSection.jsx";
import StatusPie from "./components/StatusPie.jsx";
import BrowseOverview from "./components/BrowseOverview.jsx";
import TrackerBoard from "./components/TrackerBoard.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import HiringSignals from "./components/HiringSignals.jsx";
import ResumeLibrary from "./components/ResumeLibrary.jsx";
import AnswersTab, { Tuning } from "./components/AnswersTab.jsx";
import IngredientsPanel from "./components/IngredientsPanel.jsx";
import RulesPanel from "./components/RulesPanel.jsx";
import QueueStrip from "./components/QueueStrip.jsx";
import JobsView from "./components/JobsView.jsx";
import Inbox from "./components/Inbox.jsx";
import ProfileReadiness from "./components/ProfileReadiness.jsx";
import Updates from "./components/Updates.jsx";

const TABS = [["inbox", "Inbox"], ["browse", "Browse"], ["jobs", "Jobs"], ["applied", "Applications"], ["hiring", "Hiring"],
              ["resumes", "Résumés"], ["memory", "Memory"]];
const MEMORY_PARTS = [["answers", "Answers"], ["story", "Your story"], ["rules", "Rules"], ["tuning", "Tuning"]];

// The open tab lives in the URL hash, so a reload, a bookmark or Back lands where you were.
const TAB_KEYS = TABS.map(([k]) => k);
const readHash = () => window.location.hash.replace(/^#\/?/, "").split("/");

function useHashTab() {
  const [tab, set] = useState(() => (TAB_KEYS.includes(readHash()[0]) ? readHash()[0] : "browse"));
  useEffect(() => {
    const on = () => { const t = readHash()[0]; if (TAB_KEYS.includes(t)) set(t); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const setTab = useCallback((t) => {
    set(t);
    if (readHash()[0] !== t) window.history.pushState(null, "", `#${t}`);
  }, []);
  return [tab, setTab];
}

function Memory() {
  const [part, setPartState] = useState(() => {
    const p = readHash()[1];
    return MEMORY_PARTS.some(([k]) => k === p) ? p : "answers";
  });
  const setPart = (p) => { setPartState(p); window.history.replaceState(null, "", `#memory/${p}`); };
  return (
    <section aria-label="Memory">
      <h1 className="view-title">Memory</h1>
      <p className="view-sub">What the apply agent knows about you and reuses on every application. Edit anything that's wrong.</p>
      <div className="segmented" role="group" aria-label="Memory section">
        {MEMORY_PARTS.map(([k, l]) => <button key={k} aria-pressed={part === k} onClick={() => setPart(k)}>{l}</button>)}
      </div>
      {part === "answers" && <AnswersTab />}
      {part === "story" && (
        <>
          <p className="view-sub">Used to write essays and free-text answers.</p>
          <AnswersTab only="story" />
          <IngredientsPanel />
        </>
      )}
      {part === "rules" && <RulesPanel />}
      {part === "tuning" && <Tuning />}
    </section>
  );
}

function InboxPage({ onNeeds, onUnread, onGoJobs, onOpenJob, onShowJobs, onChange }) {
  const [tick, setTick] = useState(0);
  const [inboxKey, setInboxKey] = useState(0);
  return (
    <section aria-label="Inbox" className="inbox-page">
      <h1 className="view-title">Inbox</h1>
      <p className="view-sub">Only what the apply agent can't do without you, then everything it did.</p>
      <ProfileReadiness tick={tick} onChange={() => setInboxKey((k) => k + 1)} />
      <Inbox key={inboxKey} embedded onCount={onNeeds} onGoJobs={onGoJobs} onSubmitted={() => setTick((t) => t + 1)} />
      <Updates onOpenJob={onOpenJob} onShowJobs={onShowJobs} onUnread={onUnread} onChange={onChange} />
    </section>
  );
}

export default function App() {
  const [tab, setTab] = useHashTab();
  const [filters, setFilters] = useState({ sort: "embed", india: true });
  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);
  const [trackerTick, setTrackerTick] = useState(0);
  const [queue, setQueue] = useState({ items: [] });
  const [needs, setNeeds] = useState(null);
  const [unread, setUnread] = useState(0);
  const [focusJobs, setFocusJobs] = useState(null);

  const reload = useCallback(() => {
    Promise.all([fetchJobs(filters), fetchStats()])
      .then(([feed, s]) => { setJobs(feed.jobs); setStats(s); setError(null); })
      .catch((e) => setError(String(e)));
  }, [filters]);

  useEffect(() => { reload(); }, [reload]);
  const reloadStats = useCallback(() => fetchStats().then(setStats).catch(() => {}), []);   // the donut and header counts only

  const reloadAll = useCallback(() => { reload(); setTrackerTick((t) => t + 1); }, [reload]);

  const loadQueue = useCallback(() => fetchQueue().then(setQueue).catch(() => {}), []);
  useEffect(() => { loadQueue(); }, [loadQueue]);
  const loadBadge = useCallback(() => {
    fetchInbox().then((b) => setNeeds((b.questions?.length || 0) + (b.guesses?.length || 0) + (b.bank?.length || 0))).catch(() => {});
    fetchNotifications().then((d) => setUnread(d?.unread || 0)).catch(() => {});
  }, []);
  useEffect(() => {                    // the Inbox badge stays current on every tab
    loadBadge();
    const t = setInterval(loadBadge, 30_000);
    return () => clearInterval(t);
  }, [loadBadge]);
  // Poll while the runner works so rows and the strip follow it job by job.
  useEffect(() => {
    if (!queue.running) return undefined;
    const t = setInterval(() => { loadQueue(); reloadAll(); }, 3000);
    return () => clearInterval(t);
  }, [queue.running, loadQueue, reloadAll]);

  // Every queue action returns the new snapshot; anything else -> refetch.
  const onQueueChange = (p) =>
    p.then((snap) => (snap && Array.isArray(snap.items) ? setQueue(snap) : loadQueue()))
      .then(reloadAll)
      .catch((e) => setError(String(e)));
  const onQueue = (id) => onQueueChange(addToQueue(id));
  const onApply = (id) => onQueueChange(addToQueue(id, { front: true, start: true }));

  return (
    <div className="app">
      <header className="topbar">
        <p className="brand">
          <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden="true">
            <rect width="24" height="24" rx="7" />
            <path d="M7 15.5l4-4 2.5 2.5L17.5 9" />
            <circle cx="17.5" cy="9" r="1.6" />
          </svg>
          Job dashboard
        </p>
        <nav className="tabs" aria-label="Sections">
          {TABS.map(([k, label]) => (
            <button key={k} className="tab" aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>
              {label}
              {k === "inbox" && (needs || 0) + unread > 0 && (
                <span className={needs ? "count" : "count count-quiet"} aria-label={`${needs || 0} waiting, ${unread} new`}>{(needs || 0) + unread}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="topbar-actions">
          <ThemeToggle />
          <RefreshButton onDone={reloadAll} />
        </div>
      </header>
      <QueueStrip queue={queue} onChange={onQueueChange} onOpenJob={setSelectedId} />
      {error && <div role="alert" className="alert">{error}</div>}
      <main className="view" key={tab}>
        {tab === "inbox" && (
          <InboxPage onNeeds={setNeeds} onUnread={setUnread} onGoJobs={() => setTab("jobs")} onOpenJob={setSelectedId}
            onShowJobs={(ids) => { setFocusJobs(ids); setTab("jobs"); }} onChange={() => { loadQueue(); reloadAll(); }} />
        )}
        {tab === "browse" && (
          <section aria-label="Browse" data-testid="feed-slot">
            <h1 className="view-title">Browse</h1>
            {stats && <p className="view-sub" data-testid="stats">{stats.total} jobs · {stats.new} new</p>}
            <section aria-label="Filters" style={{ marginBottom: 20 }}>
              <FilterBar filters={filters} setFilters={setFilters} />
            </section>
            <BrowseOverview stats={stats} onIndustry={(ind) => setFilters((f) => ({ ...f, industry: ind }))} />
            <Feed jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} onApply={onApply} onQueue={onQueue} queue={queue} />
            <DuplicatesSection />
          </section>
        )}
        {tab === "jobs" && <JobsView queue={queue} onApply={onApply} onOpen={setSelectedId} refreshTick={trackerTick}
          focusIds={focusJobs} onClearFocus={() => setFocusJobs(null)}
          onQueued={(snap) => { setQueue(snap); reloadAll(); }} />}
        {tab === "applied" && (
          <section aria-label="Applications">
            <h1 className="view-title">Applications</h1>
            <p className="view-sub">Mark what happened. Outcomes show which applications work.</p>
            <StatusPie stats={stats} />
            <TrackerBoard onSelect={setSelectedId} refreshTick={trackerTick} onStatsChange={reload} onStatsPoll={reloadStats} onRequeue={onQueue} />
          </section>
        )}
        {tab === "hiring" && (
          <section aria-label="Hiring">
            <h1 className="view-title">Hiring</h1>
            <HiringSignals onOpenJob={setSelectedId} />
          </section>
        )}
        {tab === "resumes" && (
          <section aria-label="Résumés">
            <h1 className="view-title">Résumés</h1>
            <ResumeLibrary />
          </section>
        )}
        {tab === "memory" && <Memory />}
      </main>
      {selectedId && <JobDetail id={selectedId} onApply={onApply} onStatusChange={() => reloadAll()} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
