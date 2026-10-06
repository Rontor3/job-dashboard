import React, { useCallback, useEffect, useRef, useState } from "react";
import AgentLiveView from "./AgentLiveView.jsx";
import AgentRunHistory from "./AgentRunHistory.jsx";
import QuestionsPanel from "./QuestionsPanel.jsx";
import MailPanel from "./MailPanel.jsx";
import MailBar from "./MailBar.jsx";
import { fetchTracker, patchStatus, fetchApplyAgentStatus, fetchOpenCounts, fetchJob } from "../api.js";
import { cleanJd } from "../cleanJd.js";
import { reasonText } from "../queueReasons.js";

// Stage menu: interviewing carries its round ("interviewing:2").
const ROUNDS = [1, 2, 3, 4, 5];
const STAGE_OPTS = [
  ["saved", "Queued"], ["applied", "Applied"], ["failed", "Failed"],
  ...ROUNDS.map((n) => [`interviewing:${n}`, `Round ${n}`]),
  ["offer", "Selected"], ["rejected", "Rejected"],
];
const STAGE_LABEL = { saved: "Queued", applied: "Applied", failed: "Failed", interviewing: "Interviewing",
                      offer: "Selected", rejected: "Rejected" };
const STAGE_COLOR = {
  saved: { bg: "var(--ring-track)", fg: "var(--ink-soft)" },
  applied: { bg: "var(--gold)", fg: "var(--gold-ink)" },
  failed: { bg: "var(--dupe-bg)", fg: "var(--dupe-ink)" },
  interviewing: { bg: "var(--green-tint)", fg: "var(--green-mid)" },
  offer: { bg: "var(--green)", fg: "#FFFFFF" },
  rejected: { bg: "var(--dupe-bg)", fg: "var(--dupe-ink)" },
};
// Row order: what needs you first (queued, failed), then the further-along ones.
const STAGE_ORDER = ["saved", "failed", "applied", "interviewing", "offer"];

const stageValue = (job) => (job.status === "interviewing" ? `interviewing:${job.interview_round || 1}` : job.status);

function stageText(job) {
  if (job.status === "interviewing") return `Round ${job.interview_round || 1}`;
  if (job.status === "failed" && job.queue_reason) return `Failed — ${reasonText(job.queue_reason)}`;
  if (job.status === "saved" && job.queue_state === "running") return "Filling…";
  return STAGE_LABEL[job.status] || job.status;
}

function StagePill({ job }) {
  const c = STAGE_COLOR[job.status] || STAGE_COLOR.saved;
  return (
    <span data-testid={`status-pill-${job.id}`}
          style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: "var(--radius-pill)",
                   background: c.bg, color: c.fg, whiteSpace: "nowrap" }}>
      {stageText(job)}
    </span>
  );
}

function JobDescription({ jobId }) {
  const [text, setText] = useState(null);
  const load = (e) => {
    if (e.target.open && text === null) {
      fetchJob(jobId).then((j) => setText(cleanJd(j.description || "") || "No description saved."))
        .catch(() => setText("Couldn't load the description."));
    }
  };
  return (
    <details onToggle={load}>
      <summary style={{ fontSize: 12, color: "var(--ink-soft)", cursor: "pointer" }}>Job description</summary>
      <div style={{ marginTop: 6, padding: "8px 12px", background: "var(--canvas)", borderRadius: 8,
                    border: "0.5px solid var(--hairline)", fontSize: 12, lineHeight: 1.55, whiteSpace: "pre-wrap",
                    maxHeight: 320, overflowY: "auto", color: "var(--ink)" }}>
        {text === null ? "Loading…" : text}
      </div>
    </details>
  );
}

function AgentLiveTag({ jobId, agentStatus }) {
  if (!agentStatus || !agentStatus.running) return null;
  return (
    <span data-testid={`status-pill-${jobId}`}
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 600,
                   padding: "3px 10px", borderRadius: "var(--radius-pill)",
                   background: "var(--green-tint)", color: "var(--green-mid)", whiteSpace: "nowrap" }}>
      <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)",
                                        animation: "breathe 2.2s ease-in-out infinite" }} />
      Filling{agentStatus.title ? ` — ${agentStatus.title}` : "…"}
    </span>
  );
}

function Row({ job, agentStatus, onSelect, onMove, onRequeue, expanded, onToggle, openCount, onChanged }) {
  const running = agentStatus && agentStatus.running && agentStatus.job_id === job.id;
  return (
    <div>
    <div
      onClick={() => onToggle(job.id)}
      aria-expanded={!!expanded}
      style={{
        display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", cursor: "pointer",
        background: "var(--card)", border: running ? "1.5px solid var(--green)" : "0.5px solid var(--hairline)",
        borderRadius: 10, transition: "transform var(--dur-quick) ease-out",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.transform = "translateX(3px)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)", overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {job.title}
        </div>
        <div style={{ fontSize: 11, color: "var(--ink-soft)", overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {job.company}{job.industry ? ` · ${job.industry}` : ""}
        </div>
      </div>
      {openCount > 0 && (
        <span data-testid={`open-badge-${job.id}`}
              style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: "var(--radius-pill)",
                       background: "var(--warm-tint)", color: "var(--warm-ink)", whiteSpace: "nowrap" }}>
          {openCount} to answer
        </span>
      )}
      {running ? <AgentLiveTag jobId={job.id} agentStatus={agentStatus} /> : <StagePill job={job} />}
      {job.status === "failed" && onRequeue && (
        <button type="button" data-testid={`requeue-${job.id}`} title="Put this job back on the apply queue (after you've corrected what stopped it)"
                onClick={(e) => { e.stopPropagation(); onRequeue(job.id); }}
                style={{ border: "none", cursor: "pointer", fontSize: 11, padding: "4px 12px", whiteSpace: "nowrap",
                         borderRadius: "var(--radius-pill)", background: "var(--green)", color: "#FFFFFF" }}>
          Re-queue
        </button>
      )}
      <select
        data-testid={`stage-${job.id}`}
        value={stageValue(job)}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => {
          const val = e.target.value;
          e.stopPropagation();
          if (val === "__remove__") return onMove(job.id, null);
          const [status, round] = val.split(":");
          onMove(job.id, status, round ? Number(round) : null);
        }}
        style={{ fontSize: 11, border: "0.5px solid var(--hairline)", borderRadius: 6,
                 padding: "3px 6px", background: "var(--canvas)", color: "var(--ink-soft)" }}
      >
        {STAGE_OPTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        <option value="__remove__">Remove from board</option>
      </select>
    </div>
    {running && <AgentLiveView jobId={job.id} status={agentStatus} />}
    {expanded && (
      <div data-testid={`expand-${job.id}`}
           style={{ margin: "6px 0 2px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
        <div><button onClick={() => onSelect(job.id)}
                     style={{ border: "none", cursor: "pointer", fontSize: 11, padding: "4px 12px",
                              borderRadius: "var(--radius-pill)", background: "var(--canvas)", color: "var(--ink-soft)" }}>
          Details
        </button></div>
        <MailPanel jobId={job.id} />
        <JobDescription jobId={job.id} />
        <QuestionsPanel jobId={job.id} onChanged={onChanged} />
        <AgentRunHistory jobId={job.id} />
      </div>
    )}
    </div>
  );
}

export default function TrackerBoard({ onSelect, refreshTick, onStatsChange, onStatsPoll, onRequeue }) {
  const [board, setBoard] = useState(null);
  const [err, setErr] = useState(null);
  const [agentStatus, setAgentStatus] = useState(null);
  const [openCounts, setOpenCounts] = useState({});
  const [expandedId, setExpandedId] = useState(null);
  const alive = useRef(true);
  const timer = useRef(null);

  const loadCounts = useCallback(() => {
    fetchOpenCounts().then((c) => setOpenCounts(c || {})).catch(() => {});
  }, []);
  const load = useCallback(() => {
    fetchTracker().then(setBoard).catch((e) => setErr(String(e)));
    loadCounts();
  }, [loadCounts]);
  // A change made here (stage menu, an answer that re-queues) also moves the pie.
  const changed = useCallback(() => { load(); if (onStatsChange) onStatsChange(); }, [load, onStatsChange]);
  useEffect(() => { load(); }, [load, refreshTick]);
  // Statuses also change without you (the submit watcher, the Gmail confirmation check, a run finishing): re-read the board
  // while this tab is on screen, and the moment you come back to it.
  // (The donut is refreshed through onStatsPoll: just the counts, not the whole job feed.)
  useEffect(() => {
    const tick = () => { if (!document.hidden) { load(); if (onStatsPoll) onStatsPoll(); } };
    const t = setInterval(tick, 20000);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", tick); };
  }, [load, onStatsPoll]);

  useEffect(() => {
    const poll = () => {
      fetchApplyAgentStatus().then((s) => {
        if (!alive.current) return;
        setAgentStatus(s);
        timer.current = setTimeout(poll, 1000);
      }).catch(() => { if (alive.current) timer.current = setTimeout(poll, 1000); });
    };
    poll();
    return () => { alive.current = false; clearTimeout(timer.current); };
  }, []);

  const move = (id, status, round) => patchStatus(id, status, round).then(changed);

  if (err) return <div role="alert" style={{ color: "var(--dupe-ink)", padding: 16 }}>{err}</div>;
  if (!board) return <div style={{ padding: 24, color: "var(--ink-soft)" }}>Loading board…</div>;

  const rows = STAGE_ORDER.flatMap((stage) => (board[stage] || []).map((j) => ({ ...j, status: stage })));
  const archived = board.archived || [];

  if (rows.length === 0 && archived.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "48px 0", color: "var(--ink-soft)" }}>
        Nothing tracked yet — press Apply or + Queue on a job.
      </div>
    );
  }

  return (
    <div style={{ marginTop: 14 }}>
      <MailBar onChanged={changed} />
      {rows.length > 0 && (
        <>
          <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 8 }}>{rows.length} active</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {rows.map((j) => (
              <Row key={j.id} job={j} agentStatus={agentStatus} onSelect={onSelect} onMove={move} onRequeue={onRequeue}
              expanded={expandedId === j.id} onToggle={(id) => setExpandedId(expandedId === id ? null : id)}
              openCount={openCounts[j.id] || 0} onChanged={changed} />
            ))}
          </div>
        </>
      )}
      <details style={{ marginTop: 14 }}>
        <summary style={{ fontSize: 12, color: "var(--ink-soft)", cursor: "pointer" }}>
          Archived ({archived.length})
        </summary>
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
          {archived.map((j) => (
            <Row key={j.id} job={{ ...j, status: j.status || "rejected" }}
                 agentStatus={agentStatus} onSelect={onSelect} onMove={move}
              expanded={expandedId === j.id} onToggle={(id) => setExpandedId(expandedId === id ? null : id)}
              openCount={openCounts[j.id] || 0} onChanged={changed} />
          ))}
        </div>
      </details>
    </div>
  );
}
