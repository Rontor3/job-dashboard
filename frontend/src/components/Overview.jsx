import React from "react";

export const WEEKLY_GOAL = 10;
const STAGES = [
  { key: "saved", label: "Saved", color: "var(--sage)" },
  { key: "applied", label: "Applied", color: "var(--green-soft)" },
  { key: "interviewing", label: "Interviewing", color: "var(--green-mid)" },
  { key: "offer", label: "Offer", color: "var(--green)" },
  { key: "rejected", label: "Rejected", color: "var(--rejected-bar)" },
];
const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: "var(--radius-card)", padding: "16px 18px" };

export default function Overview({ stats }) {
  if (!stats) return null;
  const applied = stats.applied ?? 0;
  const frac = Math.min(applied / WEEKLY_GOAL, 1);
  const dash = 2 * Math.PI * 38;
  const max = Math.max(...STAGES.map((s) => stats[s.key] ?? 0), 1);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 14, marginTop: 14 }}>
      <div style={{ ...CARD, textAlign: "center" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--green)", marginBottom: 8 }}>Applications</div>
        <svg width="92" height="92" viewBox="0 0 92 92" aria-hidden="true">
          <circle cx="46" cy="46" r="38" fill="none" stroke="var(--ring-track)" strokeWidth="9" />
          <circle cx="46" cy="46" r="38" fill="none" stroke="var(--green)" strokeWidth="9"
                  strokeDasharray={`${dash * frac} ${dash}`} strokeLinecap="round"
                  transform="rotate(-90 46 46)"
                  style={{ transition: "stroke-dasharray var(--dur-enter) var(--ease-out)" }} />
          <text x="46" y="52" textAnchor="middle" fontSize="24" fontWeight="700" fill="var(--green)">{applied}</text>
        </svg>
        <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 4 }}>Weekly goal: {WEEKLY_GOAL}</div>
      </div>
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--green)", marginBottom: 10 }}>Job search pipeline</div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, color: "var(--ink-soft)" }}>
          <tbody>
            {STAGES.map((s) => {
              const n = stats[s.key] ?? 0;
              return (
                <tr key={s.key}>
                  <td style={{ width: 92, padding: "3px 0", fontWeight: 500 }}>{s.label}</td>
                  <td>
                    <div style={{ height: 12, width: `${(n / max) * 100}%`, minWidth: n ? 8 : 0,
                                  background: s.color, borderRadius: 6,
                                  transition: "width var(--dur-enter) var(--ease-out)" }} />
                  </td>
                  <td style={{ width: 28, textAlign: "right", fontWeight: 600, color: "var(--green)" }}>{n}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
