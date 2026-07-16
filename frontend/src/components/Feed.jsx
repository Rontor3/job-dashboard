import React from "react";
import ScoreBadge from "./ScoreBadge.jsx";

function monogram(company) {
  return (company || "?").slice(0, 2);
}

const PILL = { fontSize: 11, padding: "3px 10px", borderRadius: "var(--radius-pill)" };

export default function Feed({ jobs, selectedId, onSelect }) {
  if (!jobs.length) {
    return (
      <div style={{ textAlign: "center", padding: "48px 0", color: "var(--ink-soft)" }}>
        <p style={{ margin: 0 }}>No jobs yet — hit refresh to pull the boards.</p>
      </div>
    );
  }
  return (
    <ul style={{ listStyle: "none", margin: "12px 0 0", padding: 0, background: "var(--paper)", borderRadius: "var(--radius-card)", overflow: "hidden" }}>
      {jobs.map((j, i) => (
        <li
          key={j.id}
          role="listitem"
          onClick={() => onSelect(j.id)}
          style={{
            animation: "rowIn var(--dur-enter) var(--ease-out) both",
            animationDelay: `${i * 80}ms`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "13px 20px", cursor: "pointer",
            borderTop: i ? "0.5px solid var(--hairline)" : "none",
            background: j.id === selectedId ? "var(--pastel-lavender)" : "transparent",
            opacity: j.status === "dismissed" || j.status === "applied" ? 0.75 : 1,
            transition: "transform var(--dur-quick) ease-out, background var(--dur-quick) ease-out",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = "translateX(4px)"; e.currentTarget.style.boxShadow = "var(--hover-shadow)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "none"; }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 38, height: 38, borderRadius: 8, background: "var(--pastel-lavender)", color: "var(--pastel-lavender-ink)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 500, fontSize: 13 }}>
              {monogram(j.company)}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>
                {j.title}
                {j.status && (
                  <span style={{ ...PILL, background: "var(--pastel-peach)", color: "var(--pastel-peach-mid)", marginLeft: 8 }}>
                    {j.status}
                  </span>
                )}
              </div>
              <div className="meta" style={{ color: "var(--ink-soft)" }}>
                {j.company} · {j.location || "—"} · {j.posted_date || ""} · {j.source}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {j.verdict ? (
              <span style={{ ...PILL, background: "var(--pastel-mint)", color: "var(--pastel-mint-ink)", animation: "popIn 0.4s var(--ease-pop) both", animationDelay: `${300 + i * 100}ms` }}>
                {j.verdict}
              </span>
            ) : (
              <span style={{ ...PILL, background: "var(--paper-dim)", color: "var(--ink-faint)" }}>Ranking…</span>
            )}
            <ScoreBadge value={j.embed_score} />
          </div>
        </li>
      ))}
    </ul>
  );
}
