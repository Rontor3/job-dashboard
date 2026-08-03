import React from "react";

const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)",
               borderRadius: "var(--radius-card)", padding: "14px 16px" };

function Tile({ label, value, accent }) {
  return (
    <div style={{ ...CARD, textAlign: "center", minWidth: 92 }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--ink-soft)" }}>{label}</div>
    </div>
  );
}

export default function BrowseOverview({ stats, onIndustry }) {
  if (!stats) return null;
  const v = stats.verdict_counts || {};
  const inds = stats.top_industries || [];
  const max = Math.max(...inds.map((i) => i.count), 1);
  return (
    <div style={{ display: "flex", gap: 12, marginTop: 14, alignItems: "stretch", flexWrap: "wrap" }}>
      <Tile label="Strong" value={v["Strong Fit"] ?? 0} accent="var(--gold-ink)" />
      <Tile label="Good" value={v["Good Fit"] ?? 0} accent="var(--green-mid)" />
      <Tile label="New" value={stats.new ?? 0} accent="var(--green)" />
      <div style={{ ...CARD, flex: 1, minWidth: 240 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--green)", marginBottom: 8 }}>Top industries</div>
        {inds.map((i) => (
          <button key={i.industry} onClick={() => onIndustry(i.industry)}
            style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", background: "transparent",
                     border: "none", cursor: "pointer", padding: "2px 0", color: "var(--ink-soft)", fontSize: 11 }}>
            <span style={{ width: 130, textAlign: "left" }}>{i.industry}</span>
            <span style={{ flex: 1, height: 8, background: "var(--green-tint)", borderRadius: 4 }}>
              <span style={{ display: "block", height: 8, width: `${(i.count / max) * 100}%`,
                             background: "var(--green-soft)", borderRadius: 4 }} />
            </span>
            <span style={{ width: 34, textAlign: "right", color: "var(--green)", fontWeight: 600 }}>{i.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
