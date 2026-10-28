import React, { useCallback, useEffect, useState } from "react";
import { fetchInsightBacklog } from "../api.js";
import InsightBox from "./InsightBox.jsx";

// Open and unsure answers across every application, grouped by what they ask, biggest first: one note beside a group
// teaches the cause once (a default, a fact, a wording, a field's meaning) instead of fixing forms one by one.
export default function InsightBacklog({ limit = 5 }) {
  const [groups, setGroups] = useState(null);
  const load = useCallback(() => fetchInsightBacklog(limit).then((d) => setGroups(d.groups || [])).catch(() => setGroups([])), [limit]);
  useEffect(() => { load(); }, [load]);
  if (!groups || !groups.length) return null;
  return (
    <section aria-label="Teach once, fix many" style={{ marginTop: 28 }}>
      <h2 className="section-title">Teach once, fix many</h2>
      <p className="view-sub">The same gap behind many open answers. Say what's wrong once; it applies to every later run.</p>
      <ul className="jobs">
        {groups.map((g) => (
          <li key={g.row_id} className="job" style={{ display: "block" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="fit" style={{ minWidth: 0 }}>{g.rows}×</span>
              <strong style={{ fontSize: 15 }}>{g.label}</strong>
              {g.answer && <span style={{ fontSize: 13, color: "var(--ink-soft)" }}>guessed “{g.answer}”</span>}
            </div>
            {g.examples.length > 1 && (
              <div style={{ fontSize: 12, color: "var(--ink-faint)", marginTop: 4 }}>
                also worded: {g.examples.slice(1).map((e) => `“${e.replace(/\s+/g, " ").trim()}”`).join(", ")}
              </div>
            )}
            <InsightBox q={{ id: g.row_id, label: g.label, kind: g.kind }} onDone={load} />
          </li>
        ))}
      </ul>
    </section>
  );
}
