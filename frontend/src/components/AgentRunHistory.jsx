import React, { useCallback, useEffect, useState } from "react";
import { fetchAgentRunHistory, fetchAgentLog, reviewAnswer } from "../api.js";
import EntryPicker from "./EntryPicker.jsx";

const KIND_LABEL = {
  password: "Login wall",
  email_auth: "Email verification",
  form: "Application form",
  closed: "Posting closed",
  stop: "Where it stopped",
};

const STOP_LABEL = {
  stuck: "Stuck — the screen didn't change after the last action",
  max_steps: "Hit the step limit",
  auth_wall: "Could not get past the login/registration wall",
  reached_submit_dry_run: "Reached Submit — ready for you to review and send",
  submit_declined: "Stopped before submit (declined)",
  no_advance_control: "No Next/Submit control found",
  security_email: "Account flagged by a security email — stopped",
  submitted: "Submitted — the board confirmed it",
  needs_human: "Stopped for questions you need to answer",
  dry_run: "Stopped before the submit click",
  unconfirmed: "Clicked submit, but the board didn't confirm it",
  logged_out: "Not logged in to the board",
  challenge: "Blocked by a bot check",
  no_entry: "Couldn't find the apply button",
  daily_cap: "Daily cap for this board reached",
  sensitive_field: "The form requires bank or ID details — the agent never fills or asks for these. Fill them yourself.",
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

// Where each answer came from. `tone` picks the chip colours; `reviewable` ones
// can be marked right or wrong (a wrong one is re-pointed to the right saved entry).
const ORIGIN = {
  saved_exact: { label: "From your Answers", tone: "good", reviewable: true },
  saved: { label: "From your Answers", tone: "good", reviewable: true },
  similar: { label: "Best guess from a similar answer", tone: "guess", reviewable: true },
  model: { label: "Written by the model", tone: "model", reviewable: false },
  profile: { label: "From your profile", tone: "plain", reviewable: false },
  board: { label: "Filled in by the job board", tone: "plain", reviewable: false },
  you: { label: "Your answer", tone: "plain", reviewable: false },
  open: { label: "Needs your answer", tone: "open", reviewable: false },
};
const TONE = {
  good: { bg: "var(--green-tint)", fg: "var(--green)" },
  guess: { bg: "var(--gold)", fg: "var(--gold-ink)" },
  model: { bg: "var(--peach)", fg: "var(--warm-ink)" },
  plain: { bg: "var(--canvas)", fg: "var(--ink-soft)" },
  open: { bg: "var(--dupe-bg)", fg: "var(--dupe-ink)" },
};
const BTN = { border: "none", cursor: "pointer", fontSize: 11, padding: "3px 10px", borderRadius: "var(--radius-pill)" };

function matchNote(q) {
  if (!q.matched) return null;
  const how = q.origin === "saved_exact" || q.match_kind === "exact" ? "exact wording"
    : q.score != null ? `match ${q.score}` : "";
  return `matched “${q.matched}”${how ? ` · ${how}` : ""}`;
}

// One question on a page: the question as the form worded it, the answer as it
// was filled (line breaks kept), and what produced it.
function Question({ q, onReviewed }) {
  const o = ORIGIN[q.origin] || ORIGIN.profile;
  const tone = TONE[o.tone];
  const [fixing, setFixing] = useState(null);
  const send = (verdict, entry) => reviewAnswer(q.id, verdict, entry).then(() => { setFixing(null); onReviewed(); });
  return (
    <li data-testid={`q-${q.id}`} style={{ background: "var(--canvas)", borderRadius: 8, padding: "7px 10px", fontSize: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ color: "var(--ink)", fontWeight: 600 }}>{q.label}</span>
        <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 8px", borderRadius: "var(--radius-pill)", background: tone.bg, color: tone.fg }}>
          {o.label}
        </span>
      </div>
      {q.answer ? (
        <div style={{ color: "var(--ink)", margin: "3px 0", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{q.answer}</div>
      ) : null}
      <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>
        {[matchNote(q),
          q.origin === "model" && q.confidence != null ? `confidence ${q.confidence}/100${q.basis ? ` — ${q.basis}` : ""}` : null,
          q.origin === "model" && q.unsupported_claims.length ? `not found in context: ${q.unsupported_claims.join(", ")}` : null,
          q.origin === "similar" ? "check it" : null].filter(Boolean).join(" · ")}
      </div>
      {q.prompt && (
        <details style={{ marginTop: 3 }}>
          <summary style={{ fontSize: 11, color: "var(--ink-soft)", cursor: "pointer" }}>Prompt used</summary>
          <pre style={{ margin: "4px 0 0", fontSize: 10, maxHeight: 160, overflowY: "auto", whiteSpace: "pre-wrap", color: "var(--ink-soft)" }}>{q.prompt}</pre>
        </details>
      )}
      {o.reviewable && (fixing ? (
        <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
          <EntryPicker id={`fix-${q.id}`} label={`Right question for ${q.label}`} onChange={(entry) => setFixing({ entry })} />
          <button style={{ ...BTN, background: "var(--green)", color: "#fff", whiteSpace: "nowrap" }}
                  disabled={!fixing.entry} onClick={() => send("wrong", fixing.entry)}>Save fix</button>
        </div>
      ) : q.outcome ? (
        <span style={{ fontSize: 11, fontWeight: 600, color: q.outcome === "edited" ? "var(--dupe-ink)" : "var(--green)" }}>
          {q.outcome === "edited" ? "marked wrong" : "marked correct"}
        </span>
      ) : (
        <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
          <button aria-label={`Correct: ${q.label}`} style={{ ...BTN, background: "var(--green-tint)", color: "var(--green)" }}
                  onClick={() => send("correct")}>✓ Correct</button>
          <button aria-label={`Wrong: ${q.label}`} style={{ ...BTN, background: "var(--dupe-bg)", color: "var(--dupe-ink)" }}
                  onClick={() => setFixing({ entry: null })}>✗ Wrong</button>
        </div>
      ))}
    </li>
  );
}

function Questions({ qs, onReviewed }) {
  if (!qs || qs.length === 0) return null;
  return (
    <ul aria-label="Questions on this page" style={{ margin: "8px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
      {qs.map((q) => <Question key={q.id} q={q} onReviewed={onReviewed} />)}
    </ul>
  );
}

// The last run, page by page: what the page was, where the agent stopped, a
// screenshot, and every question on it with its answer and where that came from.
export default function AgentRunHistory({ jobId }) {
  const [run, setRun] = useState(undefined); // undefined = loading, null = no run yet
  const load = useCallback(() => {
    fetchAgentRunHistory(jobId).then((body) => setRun(body || null)).catch(() => setRun(null));
  }, [jobId]);

  useEffect(() => { setRun(undefined); load(); }, [load]);

  if (!run || !run.steps || run.steps.length === 0) return null;
  const steps = run.steps;
  const unpaged = run.unpaged || [];

  return (
    <div style={{ marginTop: 12, borderTop: "0.5px solid var(--hairline)", paddingTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)", marginBottom: 8 }}>
        Last agent run
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
        {steps.map((s) => {
          const stuck = !!s.stopped_reason && !["reached_submit_dry_run", "submitted"].includes(s.stopped_reason);
          return (
            <li key={s.step} data-testid={`page-${s.step}`} style={{
              borderRadius: 10, padding: "8px 12px",
              background: stuck ? "var(--warm-tint)" : "var(--card)",
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
                  Stuck on: {s.pending_human.map((f) => (typeof f === "string" ? f : f.label || f.ref)).join(", ")}
                </div>
              )}
              {s.screenshot && (
                <a href={s.screenshot} target="_blank" rel="noreferrer">
                  <img src={s.screenshot} alt={`Screenshot of page ${s.step + 1}`}
                       style={{ marginTop: 6, maxWidth: "100%", maxHeight: 160, borderRadius: 6, display: "block" }} />
                </a>
              )}
              <Questions qs={s.questions} onReviewed={load} />
            </li>
          );
        })}
      </ul>
      {unpaged.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--ink)" }}>Other questions in this run</div>
          <Questions qs={unpaged} onReviewed={load} />
        </div>
      )}
      <RunLog jobId={jobId} />
    </div>
  );
}
