import React, { useCallback, useEffect, useState } from "react";
import { fetchJobs, fetchStats, fetchQueue, addToQueue } from "./api.js";
import FilterBar from "./components/FilterBar.jsx";
import Feed from "./components/Feed.jsx";
import JobDetail from "./components/JobDetail.jsx";
import RefreshButton from "./components/RefreshButton.jsx";
import DuplicatesSection from "./components/DuplicatesSection.jsx";
import Overview from "./components/Overview.jsx";
import BrowseOverview from "./components/BrowseOverview.jsx";
import TrackerBoard from "./components/TrackerBoard.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import HeaderScene from "./components/HeaderScene.jsx";
import HiringSignals from "./components/HiringSignals.jsx";
import ResumeLibrary from "./components/ResumeLibrary.jsx";
import AnswersTab from "./components/AnswersTab.jsx";
import QueuePanel from "./components/QueuePanel.jsx";

function TabButton({ active, onClick, label }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      style={{
        width: "100%",
        textAlign: "left",
        background: active ? "var(--green)" : "transparent",
        color: active ? "var(--peach)" : "var(--ink-soft)",
        border: "none",
        borderRadius: 10,
        padding: "8px 12px",
        fontSize: 13,
        fontWeight: 600,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("browse");
  const [filters, setFilters] = useState({ sort: "embed", india: true });
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);
  const [trackerTick, setTrackerTick] = useState(0);
  const [queue, setQueue] = useState({ items: [] });

  const reload = useCallback(() => {
    Promise.all([fetchJobs(filters), fetchStats()])
      .then(([feed, s]) => {
        setJobs(feed.jobs); setTotal(feed.total); setStats(s); setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [filters]);

  useEffect(() => { reload(); }, [reload]);

  const reloadAll = useCallback(() => { reload(); setTrackerTick((t) => t + 1); }, [reload]);

  const loadQueue = useCallback(() => fetchQueue().then(setQueue).catch(() => {}), []);
  useEffect(() => { loadQueue(); }, [loadQueue]);
  // Poll while the runner works so rows and the panel follow it job by job.
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

  const TABS = [["browse", "Browse"], ["tracker", "Tracker"], ["hiring", "Hiring Signals"],
                ["resumes", "Résumés"], ["answers", "Answers"]];

  return (
    <div className="layout">
      <aside className="sidebar">
        <header style={{ background: "var(--warm-band)", borderRadius: "var(--radius-card)", padding: "14px 16px", position: "relative", overflow: "hidden" }}>
          <HeaderScene />
          <div style={{ position: "relative" }}>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--green)", margin: 0 }}>Job dashboard</h1>
            {stats && (
              <span data-testid="stats" style={{ fontSize: 12, color: "var(--ink-soft)" }}>
                <span aria-hidden="true" style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: "var(--green-soft)", marginRight: 5, animation: "breathe 2.2s ease-in-out infinite" }} />
                {stats.total} jobs · {stats.new} new
              </span>
            )}
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
              <ThemeToggle />
              <RefreshButton onDone={reloadAll} />
            </div>
          </div>
        </header>
        <nav aria-label="Sections" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {TABS.map(([key, label]) => (
            <TabButton key={key} active={activeTab === key} onClick={() => setActiveTab(key)} label={label} />
          ))}
        </nav>
        {activeTab === "browse" && (
          <section aria-label="Filters">
            <p className="sidebar-label">Filters</p>
            <FilterBar filters={filters} setFilters={setFilters} stacked />
          </section>
        )}
        <QueuePanel queue={queue} onChange={onQueueChange} onOpenJob={setSelectedId} />
      </aside>
      <main style={{ minWidth: 0 }}>
        {error && <div role="alert" style={{ color: "var(--dupe-ink)", background: "var(--dupe-bg)", borderRadius: 12, padding: "10px 14px", marginBottom: 12 }}>{error}</div>}
        {activeTab === "hiring" ? (
          <HiringSignals onOpenJob={setSelectedId} />
        ) : activeTab === "resumes" ? (
          <ResumeLibrary />
        ) : activeTab === "answers" ? (
          <AnswersTab />
        ) : activeTab === "browse" ? (
          <div data-testid="feed-slot">
            <BrowseOverview stats={stats} onIndustry={(ind) => setFilters((f) => ({ ...f, industry: ind }))} />
            <Feed jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} onApply={onApply} onQueue={onQueue} queue={queue} />
            <DuplicatesSection />
          </div>
        ) : (
          <div>
            <Overview stats={stats} />
            <TrackerBoard onSelect={setSelectedId} refreshTick={trackerTick} />
          </div>
        )}
        {selectedId && <JobDetail id={selectedId} onStatusChange={() => reloadAll()} onClose={() => setSelectedId(null)} />}
      </main>
    </div>
  );
}
