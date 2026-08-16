import React, { useCallback, useEffect, useState } from "react";
import { fetchJobs, fetchStats, patchStatus } from "./api.js";
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

function TabButton({ active, onClick, label }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      style={{
        background: active ? "var(--green)" : "transparent",
        color: active ? "var(--peach)" : "var(--ink-soft)",
        border: "0.5px solid var(--hairline)",
        borderRadius: "var(--radius-pill)",
        padding: "6px 14px",
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
  const [filters, setFilters] = useState({ sort: "embed" });
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);
  const [trackerTick, setTrackerTick] = useState(0);

  const reload = useCallback(() => {
    Promise.all([fetchJobs(filters), fetchStats()])
      .then(([feed, s]) => {
        setJobs(feed.jobs); setTotal(feed.total); setStats(s); setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [filters]);

  useEffect(() => { reload(); }, [reload]);

  const reloadAll = useCallback(() => { reload(); setTrackerTick((t) => t + 1); }, [reload]);

  const onTrack = (id) => patchStatus(id, "saved").then(reload);

  return (
    <div className="shell">
      <header style={{ background: "var(--warm-band)", borderRadius: "var(--radius-card)", padding: "16px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", position: "relative", overflow: "hidden" }}>
        <HeaderScene />
        <div style={{ position: "relative" }}>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--green)", margin: 0 }}>
            Job dashboard
          </h1>
          {stats && (
            <span data-testid="stats" style={{ fontSize: 12, color: "var(--ink-soft)" }}>
              <span aria-hidden="true" style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: "var(--green-soft)", marginRight: 5, animation: "breathe 2.2s ease-in-out infinite" }} />
              {stats.total} jobs · {stats.new} new
            </span>
          )}
        </div>
        <div style={{ position: "relative", display: "flex", gap: 8, alignItems: "center" }}>
          <TabButton active={activeTab === "browse"} onClick={() => setActiveTab("browse")} label="Browse" />
          <TabButton active={activeTab === "tracker"} onClick={() => setActiveTab("tracker")} label="Tracker" />
          <TabButton active={activeTab === "hiring"} onClick={() => setActiveTab("hiring")} label="Hiring Signals" />
          <TabButton active={activeTab === "resumes"} onClick={() => setActiveTab("resumes")} label="Résumés" />
        </div>
        <div style={{ position: "relative", display: "flex", gap: 8, alignItems: "center" }}>
          <ThemeToggle />
          <RefreshButton onDone={reloadAll} />
        </div>
      </header>
      {error && <div role="alert" style={{ color: "var(--dupe-ink)", background: "var(--dupe-bg)", borderRadius: 12, padding: "10px 14px", marginTop: 12 }}>{error}</div>}
      <main>
        {activeTab === "hiring" ? (
          <HiringSignals />
        ) : activeTab === "resumes" ? (
          <ResumeLibrary />
        ) : activeTab === "browse" ? (
          <div data-testid="feed-slot">
            <BrowseOverview stats={stats} onIndustry={(ind) => setFilters((f) => ({ ...f, industry: ind }))} />
            <FilterBar filters={filters} setFilters={setFilters} />
            <Feed jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} onTrack={onTrack} />
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
