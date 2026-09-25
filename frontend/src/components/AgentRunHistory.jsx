import React, { useEffect, useState } from "react";
import { fetchAgentRunHistory, fetchAgentLog } from "../api.js";

const KIND_LABEL = {
  password: "Login wall",
  email_auth: "Email verification",
  form: "Application form",
  closed: "Posting closed",
};

const STOP_LABEL = {
  stuck: "Stuck — the screen didn't change after the last action",
  max_steps: "Hit the step limit",
  auth_wall: "Could not get past the login/registration wall",
  reached_submit_dry_run: "Reached Submit — ready for you to review and send",
  submit_declined: "Stopped before submit (declined)",
  no_advance_control: "No Next/Submit control found",
  security_email: "Account flagged by a security email — stopped",
};

function stopLabel(reason) {
  if (!reason) return null;
  if (STOP_LABEL[reason]) return STOP_LABEL[reason];
  if (reason.startsWith("gate:")) return `Blocked by ${reason.slice(5)}`;
  return reason;
}

function gateNoticeLabel(notice) {
  if (!notice) return null;
  if (!notice.attempted) return "Telegram: not notified (not configured)";
  if (!notice.sent) return "Telegram: send failed";
  return notice.resolved ? "Telegram: sent, resolved" : "Telegram: sent, unresolved";
}

function RunLog({ jobId }) {
  const [lines, setLines] = useState(null);
  const load = (e) => {
    if (e.target.open && lines === null) {
      fetchAgentLog(jobId, 300).then((b) => setLines(b ? b.lines : [])).catch(() => setLines([]));
    }
  };
  return (
    <details onToggle={load} style={{ marginTop: 10 }}>
      <summary style={{ fontSize: 12, color: "var(--ink-soft)", cursor: "pointer" }}>Run log</summary>
      <pre aria-label="Agent run log" style={{ margin: "6px 0 0", padding: "8px 10px", background: "var(--canvas)",
        border: "0.5px solid var(--hairline)", borderRadius: 8, fontSize: 11, lineHeight: 1.5, maxHeight: 260,
        overflowY: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word", color: "var(--ink-soft)" }}>
        {lines === null ? "Loading…" : lines.length ? lines.join("\n") : "No log output."}
      </pre>
    </details>
  );
}

export default function AgentRunHistory({ jobId }) {
  const [steps, setSteps] = useState(undefined); // undefined = loading, null = no run yet

  useEffect(() => {
    let cancelled = false;
    setSteps(undefined);
    fetchAgentRunHistory(jobId)
      .then((body) => { if (!cancelled) setSteps(body ? body.steps : null); })
      .catch(() => { if (!cancelled) setSteps(null); });
    return () => { cancelled = true; };
  }, [jobId]);

  if (steps === undefined || steps === null || steps.length === 0) return null;

  return (
    <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 8 }}>
        Last agent run
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
        {steps.map((s) => {
          const stuck = !!s.stopped_reason && s.stopped_reason !== "reached_submit_dry_run";
          return (
            <li key={s.step} style={{
              borderRadius: 10, padding: "8px 12px",
              background: stuck ? "var(--warm-tint)" : "var(--canvas)",
              border: "0.5px solid var(--hairline)",
            }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: stuck ? "var(--warm-ink)" : "var(--ink)" }}>
                Page {s.step + 1} — {KIND_LABEL[s.kind] || s.kind || "unknown"}
                {s.cred_action && ` (${s.cred_action})`}
              </div>
              {s.stopped_reason && (
                <div style={{ fontSize: 12, color: stuck ? "var(--warm-ink)" : "var(--green-mid)", marginTop: 2 }}>
                  {stopLabel(s.stopped_reason)}
                </div>
              )}
              {s.gate_notice && (
                <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 2 }}>
                  {gateNoticeLabel(s.gate_notice)}
                </div>
              )}
              {s.pending_human && s.pending_human.length > 0 && (
                <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 2 }}>
                  Stuck on: {s.pending_human.map((f) => f.label || f.ref).join(", ")}
                </div>
              )}
              {s.screenshot && (
                <a href={s.screenshot} target="_blank" rel="noreferrer">
                  <img src={s.screenshot} alt={`Screenshot of page ${s.step + 1}`}
                       style={{ marginTop: 6, maxWidth: "100%", maxHeight: 160, borderRadius: 6, display: "block" }} />
                </a>
              )}
            </li>
          );
        })}
      </ul>
      <RunLog jobId={jobId} />
    </div>
  );
}
