import React from "react";
import { CheckIcon } from "./icons.jsx";

const CHIPS = [
  { key: "remote", label: "Remote", on: { background: "var(--pastel-mint)", color: "var(--pastel-mint-ink)" } },
  { key: "job_type", label: "Full-time", value: "fulltime", on: { background: "var(--pastel-pink)", color: "var(--pastel-pink-ink)" } },
  { key: "status", label: "Saved", value: "saved", on: { background: "var(--pastel-peach)", color: "var(--pastel-peach-ink)" } },
];

export default function FilterBar({ filters, setFilters }) {
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
        style={{ flex: 1, minWidth: 150, border: "none", background: "var(--paper)", borderRadius: "var(--radius-pill)", padding: "8px 14px", fontSize: 13, color: "var(--ink)" }}
      />
      {CHIPS.map((c) => {
        const active = filters[c.key] === (c.value ?? true);
        return (
          <button
            key={c.label}
            onClick={() => toggle(c.key, c.value ?? true)}
            style={{
              border: "none", cursor: "pointer", fontSize: 12, padding: "6px 12px",
              borderRadius: "var(--radius-pill)",
              transition: "transform var(--dur-quick) ease-out",
              ...(active ? c.on : { background: "var(--paper)", color: "var(--ink-soft)" }),
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
          style={{ border: "none", background: "var(--paper)", borderRadius: 8, padding: "4px 8px", fontSize: 12 }}
        >
          <option value="embed">match score</option>
          <option value="llm">LLM score</option>
          <option value="date">newest</option>
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
