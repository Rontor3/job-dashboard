import React, { useEffect, useState } from "react";
import { fetchJob, patchStatus } from "../api.js";
import { XIcon, ArrowUpRightIcon } from "./icons.jsx";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };

export default function JobDetail({ id, onStatusChange, onClose }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setJob(null);
    setError(null);
    fetchJob(id)
      .then((j) => { if (!cancelled) setJob(j); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [id]);

  if (error) return <div role="alert" style={{ padding: 16, color: "var(--pastel-pink-ink)" }}>{error}</div>;
  if (!job) return <div style={{ padding: 16, color: "var(--ink-faint)" }}>Loading…</div>;

  const setStatus = (status) =>
    patchStatus(id, status).then(() => onStatusChange(status)).catch((e) => setError(String(e)));

  return (
    <div style={{ background: "var(--paper)", borderRadius: "var(--radius-card)", padding: "18px 20px", marginTop: 14, animation: "rowIn var(--dur-enter) var(--ease-out) both" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 500 }}>{job.title}</div>
          <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>{job.company} · {job.location || "—"} · via {job.source}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {job.embed_score != null && (
            <div style={{ textAlign: "center", background: "var(--pastel-lavender)", borderRadius: 14, padding: "8px 16px" }}>
              <div style={{ fontSize: 22, fontWeight: 500, color: "var(--pastel-lavender-ink)" }}>
                {job.llm_score ?? Math.round(job.embed_score * 100)}
              </div>
              <div style={{ fontSize: 10, color: "var(--pastel-lavender-mid)" }}>
                {job.llm_score != null ? `embed ${job.embed_score.toFixed(2)} · LLM ${job.llm_score}` : "embed match"}
              </div>
            </div>
          )}
          <button onClick={onClose} aria-label="Close" style={{ ...BTN, background: "var(--paper-dim)", color: "var(--ink-faint)" }}><XIcon /></button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, margin: "14px 0" }}>
        <button style={{ ...BTN, background: "var(--pastel-mint)", color: "var(--pastel-mint-ink)" }} onClick={() => setStatus("saved")}>Save</button>
        <button style={{ ...BTN, background: "var(--pastel-peach)", color: "var(--pastel-peach-ink)" }} onClick={() => setStatus("applied")}>Applied</button>
        <button style={{ ...BTN, background: "var(--paper-dim)", color: "var(--ink-faint)" }} onClick={() => setStatus("dismissed")}>Dismiss</button>
        <a href={job.job_url} target="_blank" rel="noreferrer"
           style={{ ...BTN, background: "var(--pastel-lavender)", color: "var(--pastel-lavender-ink)", marginLeft: "auto", textDecoration: "none" }}>
          Apply <ArrowUpRightIcon />
        </a>
      </div>

      {(job.strengths.length > 0 || job.gaps.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{ background: "var(--pastel-mint)", borderRadius: 12, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--pastel-mint-ink)", marginBottom: 4 }}>Strengths</div>
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: "var(--pastel-mint-mid)", lineHeight: 1.6 }}>
              {job.strengths.map((s) => <li key={s}>{s}</li>)}
            </ul>
          </div>
          <div style={{ background: "var(--pastel-peach)", borderRadius: 12, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--pastel-peach-ink)", marginBottom: 4 }}>Gaps</div>
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: "var(--pastel-peach-mid)", lineHeight: 1.6 }}>
              {job.gaps.map((g) => <li key={g}>{g}</li>)}
            </ul>
          </div>
        </div>
      )}

      {(() => {
        const flags = job.flags || {};
        const dealBreakers = flags.deal_breakers || [];
        const hasFlags = dealBreakers.length > 0 || flags.deadline != null || flags.expired;
        if (!hasFlags) return null;
        return (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
            {dealBreakers.map((d) => (
              <span key={d} style={{ fontSize: 11, background: "var(--pastel-pink)", color: "var(--pastel-pink-ink)", borderRadius: "var(--radius-pill)", padding: "4px 10px" }}>
                deal-breaker: {d}
              </span>
            ))}
            {flags.deadline != null && (
              <span style={{ fontSize: 11, background: "var(--pastel-peach)", color: "var(--pastel-peach-ink)", borderRadius: "var(--radius-pill)", padding: "4px 10px" }}>
                deadline: {flags.deadline}
              </span>
            )}
            {flags.expired && (
              <span style={{ fontSize: 11, background: "var(--pastel-pink)", color: "var(--pastel-pink-ink)", borderRadius: "var(--radius-pill)", padding: "4px 10px" }}>
                expired
              </span>
            )}
          </div>
        );
      })()}

      <div style={{ fontSize: 13, color: "var(--ink-soft)", marginTop: 12, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
        {job.description}
      </div>

      {job.cross_listings.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 10 }}>
          Also posted on: {job.cross_listings.map((c) => c.source).join(", ")}
        </div>
      )}
    </div>
  );
}
