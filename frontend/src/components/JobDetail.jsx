import React, { useEffect, useState } from "react";
import { fetchJob, patchStatus } from "../api.js";
import { XIcon, ArrowUpRightIcon } from "./icons.jsx";
import ResumePanel from "./ResumePanel.jsx";

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

  if (error) return <div role="alert" style={{ padding: 16, color: "var(--dupe-ink)" }}>{error}</div>;
  if (!job) return <div style={{ padding: 16, color: "var(--ink-faint)" }}>Loading…</div>;

  const setStatus = (status) =>
    patchStatus(id, status).then(() => onStatusChange(status)).catch((e) => setError(String(e)));

  return (
    <div style={{ background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: "var(--radius-card)", padding: "18px 20px", marginTop: 14, animation: "rowIn var(--dur-enter) var(--ease-out) both" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 500 }}>{job.title}</div>
          <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>{job.company} · {job.location || "—"} · via {job.source}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {job.embed_score != null && (
            <div style={{ textAlign: "center", background: "var(--green)", borderRadius: 14, padding: "8px 16px" }}>
              <div style={{ fontSize: 22, fontWeight: 500, color: "#FFFFFF" }}>
                {job.llm_score ?? Math.round(job.embed_score * 100)}
              </div>
              <div style={{ fontSize: 10, color: "#CFE0D8" }}>
                {job.llm_score != null ? `embed ${job.embed_score.toFixed(2)} · LLM ${job.llm_score}` : "embed match"}
              </div>
            </div>
          )}
          <button onClick={onClose} aria-label="Close" style={{ ...BTN, background: "var(--canvas)", color: "var(--ink-faint)" }}><XIcon /></button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, margin: "14px 0" }}>
        <button style={{ ...BTN, background: "var(--green-tint)", color: "var(--green)" }} onClick={() => setStatus("saved")}>Save</button>
        <button style={{ ...BTN, background: "var(--gold)", color: "var(--gold-ink)" }} onClick={() => setStatus("applied")}>Applied</button>
        <button style={{ ...BTN, background: "#F1EBE0", color: "var(--ink-faint)" }} onClick={() => setStatus("dismissed")}>Dismiss</button>
        <a href={job.job_url} target="_blank" rel="noreferrer"
           style={{ ...BTN, background: "var(--green)", color: "#FFFFFF", marginLeft: "auto", textDecoration: "none" }}>
          Apply <ArrowUpRightIcon />
        </a>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0" }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--ink-soft)" }}>Response:</span>
        <button style={{ ...BTN, background: "var(--green-tint)", color: "var(--green-mid)" }} onClick={() => setStatus("interviewing")}>Interviewing</button>
        <button style={{ ...BTN, background: "var(--green)", color: "#FFFFFF" }} onClick={() => setStatus("offer")}>Offer</button>
        <button style={{ ...BTN, background: "var(--dupe-bg)", color: "var(--dupe-ink)" }} onClick={() => setStatus("rejected")}>Rejected</button>
      </div>

      {(job.strengths.length > 0 || job.gaps.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{ background: "var(--green-tint)", borderRadius: 12, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--green)", marginBottom: 4 }}>Strengths</div>
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: "var(--green-mid)", lineHeight: 1.6 }}>
              {job.strengths.map((s) => <li key={s}>{s}</li>)}
            </ul>
          </div>
          <div style={{ background: "var(--warm-tint)", borderRadius: 12, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--warm-ink)", marginBottom: 4 }}>Gaps</div>
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: "var(--warm-ink)", lineHeight: 1.6 }}>
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
              <span key={d} style={{ fontSize: 11, background: "var(--dupe-bg)", color: "var(--dupe-ink)", borderRadius: "var(--radius-pill)", padding: "4px 10px" }}>
                deal-breaker: {d}
              </span>
            ))}
            {flags.deadline != null && (
              <span style={{ fontSize: 11, background: "var(--warm-tint)", color: "var(--warm-ink)", borderRadius: "var(--radius-pill)", padding: "4px 10px" }}>
                deadline: {flags.deadline}
              </span>
            )}
            {flags.expired && (
              <span style={{ fontSize: 11, background: "var(--dupe-bg)", color: "var(--dupe-ink)", borderRadius: "var(--radius-pill)", padding: "4px 10px" }}>
                expired
              </span>
            )}
          </div>
        );
      })()}

      <ResumePanel jobId={id} />

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
