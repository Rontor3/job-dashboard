import React from "react";
import ScoreBadge from "./ScoreBadge.jsx";

function monogram(company) {
  return (company || "?").slice(0, 2);
}

const PILL = { fontSize: 11, padding: "3px 10px", borderRadius: "var(--radius-pill)" };

export default function Feed({ jobs, selectedId, onSelect, onTrack }) {
  if (!jobs.length) {
    return (
      <div style={{ textAlign: "center", padding: "48px 0", color: "var(--ink-soft)" }}>
        <p style={{ margin: 0 }}>No jobs yet — hit refresh to pull the boards.</p>
      </div>
    );
  }
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: "10px 0 0", display: "flex", flexDirection: "column", gap: 10 }}>
      {jobs.map((j, i) => (
        <li
          key={j.id}
          role="listitem"
          onClick={() => onSelect(j.id)}
          style={{
            animation: "rowIn var(--dur-enter) var(--ease-out) both",
            animationDelay: `${i * 80}ms`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "14px 18px", cursor: "pointer",
            background: "var(--card)",
            border: j.id === selectedId ? "1.5px solid var(--green)" : "0.5px solid var(--hairline)",
            borderRadius: "var(--radius-card)",
            opacity: j.status === "dismissed" || j.status === "applied" ? 0.75 : 1,
            transition: "transform var(--dur-quick) ease-out, background var(--dur-quick) ease-out",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = "translateX(4px)"; e.currentTarget.style.boxShadow = "var(--hover-shadow)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "none"; }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 38, height: 38, borderRadius: 12, background: "var(--green)", color: "var(--peach)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 500, fontSize: 13 }}>
              {monogram(j.company)}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>
                {j.title}
                {j.status && (
                  <span style={{ ...PILL, background: "var(--green-tint)", color: "var(--green-mid)", marginLeft: 8 }}>
                    {j.status}
                  </span>
                )}
              </div>
              <div className="meta" style={{ color: "var(--ink-soft)", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                <span>{j.company} · {j.location || "—"} · {j.posted_date || ""} · {j.source}</span>
                {j.apply_type && (
                  <span
                    title={
                      j.apply_type.fill === "easy"
                        ? "One-click auto-fill works well here (company ATS form)"
                        : j.apply_type.fill === "maybe"
                          ? "Auto-fill may work — LinkedIn Easy Apply (if logged in) or an external form"
                          : "Likely manual — Naukri native/chatbot or unknown apply flow"
                    }
                    style={{
                      fontSize: 10, fontWeight: 600, padding: "1px 7px", borderRadius: "var(--radius-pill)", whiteSpace: "nowrap",
                      background: j.apply_type.fill === "easy" ? "var(--green-tint)" : j.apply_type.fill === "maybe" ? "#FBF0DC" : "#EFEAE1",
                      color: j.apply_type.fill === "easy" ? "var(--green)" : j.apply_type.fill === "maybe" ? "#9A6B12" : "var(--ink-faint)",
                    }}
                  >
                    {j.apply_type.fill === "easy" ? "⚡ " : j.apply_type.fill === "maybe" ? "◐ " : "○ "}{j.apply_type.label}
                  </span>
                )}
              </div>
              {(j.industry || j.company_type) ? (
                <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                  {j.industry && (
                    <span style={{ ...PILL, background: "#F1EBE0", color: "var(--ink-soft)" }}>{j.industry}</span>
                  )}
                  {j.company_type && (
                    <span style={{ ...PILL, background: "#F1EBE0", color: "var(--ink-soft)" }}>{j.company_type}</span>
                  )}
                </div>
              ) : (
                <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                  <span style={{ ...PILL, background: "#F1EBE0", color: "var(--ink-faint)" }}>Unclassified</span>
                </div>
              )}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {j.verdict ? (
              <span
                style={{
                  ...PILL,
                  ...(j.verdict === "Strong Fit"
                    ? { background: "var(--gold)", color: "var(--gold-ink)" }
                    : { background: "var(--green-tint)", color: "var(--green-mid)" }),
                  animation: "popIn 0.4s var(--ease-pop) both",
                  animationDelay: `${300 + i * 100}ms`,
                }}
              >
                {j.verdict}
              </span>
            ) : (
              <span style={{ ...PILL, background: "#F1EBE0", color: "var(--ink-soft)" }}>Ranking…</span>
            )}
            <ScoreBadge value={j.llm_score != null ? j.llm_score / 100 : j.embed_score} />
            {["saved","applied","interviewing","offer","rejected"].includes(j.status) ? null : (
              <button
                onClick={(e) => { e.stopPropagation(); onTrack && onTrack(j.id); }}
                style={{ ...PILL, background: "transparent", border: "1px solid var(--green)",
                         color: "var(--green)", cursor: "pointer" }}>
                + Track
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
