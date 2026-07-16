import React, { useCallback, useEffect, useState } from "react";
import { fetchJobs, fetchStats } from "./api.js";
import FilterBar from "./components/FilterBar.jsx";
import Feed from "./components/Feed.jsx";
import JobDetail from "./components/JobDetail.jsx";
import RefreshButton from "./components/RefreshButton.jsx";
import DuplicatesSection from "./components/DuplicatesSection.jsx";

export default function App() {
  const [filters, setFilters] = useState({ sort: "embed" });
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(() => {
    Promise.all([fetchJobs(filters), fetchStats()])
      .then(([feed, s]) => {
        setJobs(feed.jobs); setTotal(feed.total); setStats(s); setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [filters]);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div className="shell">
      <header style={{ background: "var(--warm-band)", borderRadius: "var(--radius-card)", padding: "16px 20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
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
        <RefreshButton onDone={reload} />
      </header>
      {error && <div role="alert" style={{ color: "var(--dupe-ink)", background: "var(--dupe-bg)", borderRadius: 12, padding: "10px 14px", marginTop: 12 }}>{error}</div>}
      <main data-testid="feed-slot">
        <FilterBar filters={filters} setFilters={setFilters} />
        <Feed jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} />
        {selectedId && <JobDetail id={selectedId} onStatusChange={() => reload()} onClose={() => setSelectedId(null)} />}
        <DuplicatesSection />
      </main>
    </div>
  );
}
