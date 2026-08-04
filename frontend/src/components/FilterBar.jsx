import React, { useEffect, useState } from "react";
import { CheckIcon } from "./icons.jsx";

const ACTIVE_CHIP = { background: "var(--green)", color: "#FFFFFF" };

const CHIPS = [
  { key: "remote", label: "Remote", on: ACTIVE_CHIP },
  { key: "job_type", label: "Full-time", value: "fulltime", on: ACTIVE_CHIP },
  { key: "status", label: "Saved", value: "saved", on: ACTIVE_CHIP },
];

// Fallback only — the real list comes from /api/classifications (distinct
// sources actually present in the feed, so naukri/wellfound show up too).
const FALLBACK_SOURCES = ["remotive", "remoteok", "himalayas", "jobspy:linkedin", "jobspy:indeed"];

export default function FilterBar({ filters, setFilters }) {
  const [classifications, setClassifications] = useState({ industries: [], company_types: [], sources: [] });

  useEffect(() => {
    fetch("/api/classifications")
      .then((r) => r.json())
      .then((d) => setClassifications({
        industries: d.industries || [],
        company_types: d.company_types || [],
        sources: d.sources || [],
      }))
      .catch(() => {});
  }, []);

  const sourceOptions = ["", ...(classifications.sources.length ? classifications.sources : FALLBACK_SOURCES)];

  const toggle = (key, value = true) =>
    setFilters((f) => {
      const next = { ...f };
      if (next[key] === value) delete next[key];
      else next[key] = value;
      return next;
    });

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", margin: "12px 0 0" }}>
      <input
        type="search"
        placeholder="Search roles, companies…"
        aria-label="Search jobs"
        onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
        style={{ flex: 1, minWidth: 150, border: "1px solid var(--hairline)", background: "var(--card)", borderRadius: "var(--radius-pill)", padding: "8px 14px", fontSize: 13, color: "var(--ink)" }}
      />
      {CHIPS.map((c) => {
        const active = filters[c.key] === (c.value ?? true);
        return (
          <button
            key={c.label}
            onClick={() => toggle(c.key, c.value ?? true)}
            style={{
              cursor: "pointer", fontSize: 12, padding: "6px 12px",
              borderRadius: "var(--radius-pill)",
              transition: "transform var(--dur-quick) ease-out",
              ...(active
                ? { border: "none", ...c.on }
                : { border: "1px solid #CBBFA9", background: "var(--card)", color: "var(--ink-soft)" }),
            }}
            onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; }}
          >
            {c.label}{active && <CheckIcon />}
          </button>
        );
      })}
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 6, alignItems: "center" }}>
        Sort
        <select
          value={filters.sort}
          onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value }))}
          style={{ border: "1px solid var(--hairline)", background: "var(--card)", color: "var(--ink-soft)", borderRadius: 8, padding: "4px 8px", fontSize: 12 }}
        >
          <option value="embed">match score</option>
          <option value="llm">LLM score</option>
          <option value="date">newest</option>
        </select>
      </label>
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 6, alignItems: "center" }}>
        Min score
        <input
          type="range"
          aria-label="Minimum match score"
          min={0}
          max={100}
          step={5}
          defaultValue={0}
          onChange={(e) => {
            const value = Number(e.target.value);
            setFilters((f) => {
              const next = { ...f };
              if (value === 0) delete next.min_score;
              else next.min_score = value / 100;
              return next;
            });
          }}
        />
        <span>{filters.min_score != null ? Math.round(filters.min_score * 100) : 0}</span>
      </label>
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 6, alignItems: "center" }}>
        Source
        <select
          aria-label="Filter by source"
          value={filters.source ?? ""}
          onChange={(e) => {
            const value = e.target.value;
            setFilters((f) => {
              const next = { ...f };
              if (!value) delete next.source;
              else next.source = value;
              return next;
            });
          }}
          style={{ border: "1px solid var(--hairline)", background: "var(--card)", color: "var(--ink-soft)", borderRadius: 8, padding: "4px 8px", fontSize: 12 }}
        >
          {sourceOptions.map((s) => (
            <option key={s} value={s}>{s === "" ? "all sources" : s}</option>
          ))}
        </select>
      </label>
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 6, alignItems: "center" }}>
        Industry
        <select
          aria-label="Filter by industry"
          value={filters.industry ?? ""}
          onChange={(e) => {
            const value = e.target.value;
            setFilters((f) => {
              const next = { ...f };
              if (!value) delete next.industry;
              else next.industry = value;
              return next;
            });
          }}
          style={{ border: "1px solid var(--hairline)", background: "var(--card)", color: "var(--ink-soft)", borderRadius: 8, padding: "4px 8px", fontSize: 12 }}
        >
          <option value="">All industries</option>
          {classifications.industries.map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </label>
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 6, alignItems: "center" }}>
        Company-type
        <select
          aria-label="Filter by company type"
          value={filters.company_type ?? ""}
          onChange={(e) => {
            const value = e.target.value;
            setFilters((f) => {
              const next = { ...f };
              if (!value) delete next.company_type;
              else next.company_type = value;
              return next;
            });
          }}
          style={{ border: "1px solid var(--hairline)", background: "var(--card)", color: "var(--ink-soft)", borderRadius: 8, padding: "4px 8px", fontSize: 12 }}
        >
          <option value="">All types</option>
          {classifications.company_types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </label>
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 4, alignItems: "center" }}>
        <input type="checkbox" checked={!!filters.include_dismissed}
          onChange={(e) => setFilters((f) => ({ ...f, include_dismissed: e.target.checked || undefined }))} />
        show dismissed
      </label>
    </div>
  );
}
