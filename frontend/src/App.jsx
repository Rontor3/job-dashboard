import React, { useCallback, useEffect, useState } from "react";
import { fetchJobs, fetchStats } from "./api.js";
import FilterBar from "./components/FilterBar.jsx";
import Feed from "./components/Feed.jsx";

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
      <header style={{ background: "var(--pastel-lavender)", borderRadius: "var(--radius-card)", padding: "16px 20px" }}>
        <h1 style={{ fontSize: 17, fontWeight: 500, color: "var(--pastel-lavender-ink)", margin: 0 }}>
          Job dashboard
        </h1>
        {stats && (
          <span data-testid="stats" style={{ fontSize: 12, color: "var(--pastel-lavender-mid)" }}>
            {stats.total} jobs · {stats.new} new
          </span>
        )}
      </header>
      {error && <div role="alert" style={{ color: "var(--pastel-pink-ink)", background: "var(--pastel-pink)", borderRadius: 12, padding: "10px 14px", marginTop: 12 }}>{error}</div>}
      <main data-testid="feed-slot">
        <FilterBar filters={filters} setFilters={setFilters} />
        <Feed jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} />
      </main>
    </div>
  );
}
