import React, { useCallback, useEffect, useRef, useState } from "react";
import AgentLiveView from "./AgentLiveView.jsx";
import AgentRunHistory from "./AgentRunHistory.jsx";
import QuestionsPanel from "./QuestionsPanel.jsx";
import AnswersUsed from "./AnswersUsed.jsx";
import { fetchTracker, patchStatus, fetchApplyAgentStatus, fetchOpenCounts } from "../api.js";

const STAGE_OPTS = ["saved", "applied", "interviewing", "offer", "rejected"];
const STAGE_LABEL = { saved: "Saved", applied: "Applied", interviewing: "Interviewing", offer: "Offer", rejected: "Rejected" };
const STAGE_COLOR = {
  saved: { bg: "#F1EBE0", fg: "var(--ink-soft)" },
  applied: { bg: "var(--gold)", fg: "var(--gold-ink)" },
  interviewing: { bg: "var(--green-tint)", fg: "var(--green-mid)" },
  offer: { bg: "var(--green)", fg: "#FFFFFF" },
  rejected: { bg: "var(--dupe-bg)", fg: "var(--dupe-ink)" },
};
// Row order: earlier stages first, so a freshly-tracked job doesn't get
// buried under everything already further along.
const STAGE_ORDER = ["saved", "applied", "interviewing", "offer"];

function StagePill({ jobId, status }) {
  const c = STAGE_COLOR[status] || STAGE_COLOR.saved;
  return (
    <span data-testid={`status-pill-${jobId}`}
          style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: "var(--radius-pill)",
                   background: c.bg, color: c.fg, whiteSpace: "nowrap" }}>
      {STAGE_LABEL[status] || status}
    </span>
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

function Row({ job, agentStatus, onSelect, onMove, expanded, onToggle, openCount, onChanged }) {
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
      {running ? <AgentLiveTag jobId={job.id} agentStatus={agentStatus} /> : <StagePill jobId={job.id} status={job.status} />}
      <select
        data-testid={`stage-${job.id}`}
        value={job.status}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => {
          const val = e.target.value;
          e.stopPropagation();
          onMove(job.id, val === "__remove__" ? null : val);
        }}
        style={{ fontSize: 11, border: "0.5px solid var(--hairline)", borderRadius: 6,
                 padding: "3px 6px", background: "var(--canvas)", color: "var(--ink-soft)" }}
      >
        {STAGE_OPTS.map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}
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
        <QuestionsPanel jobId={job.id} onChanged={onChanged} />
        <AnswersUsed jobId={job.id} />
        <AgentRunHistory jobId={job.id} />
      </div>
    )}
    </div>
  );
}

export default function TrackerBoard({ onSelect, refreshTick }) {
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
  useEffect(() => { load(); }, [load, refreshTick]);

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

  const move = (id, status) => patchStatus(id, status).then(load);

  if (err) return <div role="alert" style={{ color: "var(--dupe-ink)", padding: 16 }}>{err}</div>;
  if (!board) return <div style={{ padding: 24, color: "var(--ink-soft)" }}>Loading board…</div>;

  const rows = STAGE_ORDER.flatMap((stage) => (board[stage] || []).map((j) => ({ ...j, status: stage })));
  const archived = board.archived || [];

  if (rows.length === 0 && archived.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "48px 0", color: "var(--ink-soft)" }}>
        Nothing tracked yet — hit + Track or Apply with agent on a job.
      </div>
    );
  }

  return (
    <div style={{ marginTop: 14 }}>
      {rows.length > 0 && (
        <>
          <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 8 }}>{rows.length} tracked</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {rows.map((j) => (
              <Row key={j.id} job={j} agentStatus={agentStatus} onSelect={onSelect} onMove={move}
              expanded={expandedId === j.id} onToggle={(id) => setExpandedId(expandedId === id ? null : id)}
              openCount={openCounts[j.id] || 0} onChanged={loadCounts} />
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
              openCount={openCounts[j.id] || 0} onChanged={loadCounts} />
          ))}
        </div>
      </details>
    </div>
  );
}
