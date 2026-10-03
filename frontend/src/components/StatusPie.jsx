import React, { useState } from "react";

// Fixed entity -> slot order (never re-assigned when a status is empty), so a
// status keeps its colour as counts change. Slots validated adjacent + wrap.
export const STATUSES = [
  { key: "applied", label: "Applied", color: "var(--series-1)" },
  { key: "failed", label: "Failed", color: "var(--series-2)" },
  { key: "interviewing", label: "Interviewing", color: "var(--series-3)" },
  { key: "saved", label: "Queued", color: "var(--series-4)" },
  { key: "rejected", label: "Rejected", color: "var(--series-5)" },
  { key: "offer", label: "Selected", color: "var(--series-6)" },
];

const SIZE = 168;
const R = 64;          // ring centre radius
const W = 22;          // ring thickness
const GAP = 2;         // px of surface between slices

function arc(a0, a1) {
  const p = (a, r) => [SIZE / 2 + r * Math.sin(a), SIZE / 2 - r * Math.cos(a)];
  const ro = R + W / 2, ri = R - W / 2, big = a1 - a0 > Math.PI ? 1 : 0;
  const [x0, y0] = p(a0, ro), [x1, y1] = p(a1, ro), [x2, y2] = p(a1, ri), [x3, y3] = p(a0, ri);
  return `M${x0} ${y0} A${ro} ${ro} 0 ${big} 1 ${x1} ${y1} L${x2} ${y2} A${ri} ${ri} 0 ${big} 0 ${x3} ${y3} Z`;
}

export default function StatusPie({ stats }) {
  const [active, setActive] = useState(null);
  if (!stats) return null;
  const rows = STATUSES.map((s) => ({ ...s, n: stats[s.key] ?? 0 }));
  const total = rows.reduce((t, r) => t + r.n, 0);
  const shown = rows.filter((r) => r.n > 0);
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0);
  const gapAngle = shown.length > 1 ? GAP / R : 0;

  let a = 0;
  const slices = shown.map((r) => {
    const sweep = (r.n / total) * 2 * Math.PI;
    const s = { ...r, a0: a + gapAngle / 2, a1: a + sweep - gapAngle / 2 };
    a += sweep;
    return s;
  });
  const focus = rows.find((r) => r.key === active);

  return (
    <section aria-label="Applications by status"
             style={{ display: "flex", alignItems: "center", gap: 28, flexWrap: "wrap", marginTop: 4,
                      background: "var(--card)", border: "0.5px solid var(--hairline)",
                      borderRadius: "var(--radius-card)", padding: "16px 20px" }}>
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
           aria-label={rows.map((r) => `${r.label} ${r.n}`).join(", ")}>
        {total === 0 && (
          <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke="var(--ring-track)" strokeWidth={W} />
        )}
        {slices.length === 1 && (
          <circle data-testid="pie-slice-full" cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none"
                  stroke={slices[0].color} strokeWidth={W}
                  onMouseEnter={() => setActive(slices[0].key)} onMouseLeave={() => setActive(null)} />
        )}
        {slices.length > 1 && slices.map((s) => (
          <path key={s.key} data-testid={`pie-slice-${s.key}`} d={arc(s.a0, s.a1)} fill={s.color}
                opacity={active && active !== s.key ? 0.35 : 1}
                style={{ cursor: "default", transition: "opacity var(--dur-quick) ease-out" }}
                onMouseEnter={() => setActive(s.key)} onMouseLeave={() => setActive(null)} />
        ))}
        <text x={SIZE / 2} y={SIZE / 2 - 2} textAnchor="middle" fontSize="26" fontWeight="700" fill="var(--ink)">
          {focus ? focus.n : total}
        </text>
        <text x={SIZE / 2} y={SIZE / 2 + 18} textAnchor="middle" fontSize="11" fill="var(--ink-soft)">
          {focus ? `${focus.label} · ${pct(focus.n)}%` : "tracked"}
        </text>
      </svg>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6, minWidth: 200 }}>
        {rows.map((r) => (
          <li key={r.key} data-testid={`pie-legend-${r.key}`}
              onMouseEnter={() => r.n && setActive(r.key)} onMouseLeave={() => setActive(null)}
              style={{ display: "grid", gridTemplateColumns: "12px 1fr auto auto", alignItems: "center", gap: 10,
                       fontSize: 13, color: r.n ? "var(--ink)" : "var(--ink-faint)",
                       opacity: active && active !== r.key ? 0.5 : 1 }}>
            <span aria-hidden="true" style={{ width: 12, height: 12, borderRadius: 3, background: r.color,
                                              opacity: r.n ? 1 : 0.35 }} />
            <span>{r.label}</span>
            <span style={{ fontWeight: 600, textAlign: "right", minWidth: 24 }}>{r.n}</span>
            <span style={{ color: "var(--ink-soft)", fontSize: 11, textAlign: "right", minWidth: 32 }}>{pct(r.n)}%</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
