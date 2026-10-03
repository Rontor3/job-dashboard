import React, { useEffect, useState } from "react";
import { fetchJobMail } from "../api.js";

const LABEL = { acknowledgement: "Received", assessment: "Assessment", interview: "Interview", offer: "Offer",
                rejected: "Rejected", other: "Other" };
const TONE = { interview: "var(--green-mid)", offer: "var(--green)", rejected: "var(--dupe-ink)", assessment: "var(--warm-ink)" };

// What the company has written since you applied (found by the daily inbox scan).
export default function MailPanel({ jobId, refreshTick }) {
  const [mail, setMail] = useState(null);
  useEffect(() => { fetchJobMail(jobId).then(setMail).catch(() => setMail([])); }, [jobId, refreshTick]);
  if (!mail || mail.length === 0) return null;
  return (
    <div data-testid={`mail-${jobId}`}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", marginBottom: 6 }}>Emails from the company ({mail.length})</div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {mail.map((m) => (
          <li key={m.id} style={{ padding: "8px 12px", background: "var(--canvas)", border: "0.5px solid var(--hairline)", borderRadius: 8 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: TONE[m.category] || "var(--ink-soft)" }}>
                {LABEL[m.category] || m.category}{m.category === "interview" && m.round ? ` · round ${m.round}` : ""}
              </span>
              <span style={{ fontSize: 12, color: "var(--ink)" }}>{m.subject}</span>
              <span className="meta" style={{ color: "var(--ink-faint)", marginLeft: "auto" }}>
                {m.received_at ? new Date(m.received_at * 1000).toLocaleDateString() : ""}
              </span>
            </div>
            {m.summary && <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 2 }}>{m.summary}</div>}
          </li>
        ))}
      </ul>
    </div>
  );
}
