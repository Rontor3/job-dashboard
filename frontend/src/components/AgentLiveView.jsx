import React, { useEffect, useRef, useState } from "react";
import { fetchAgentLog } from "../api.js";

const PRE = {
  margin: 0, padding: "8px 10px", background: "var(--canvas)", color: "var(--ink-soft)",
  border: "0.5px solid var(--hairline)", borderRadius: 8, fontSize: 11, lineHeight: 1.5,
  maxHeight: 220, overflowY: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word",
};

// Live screenshot + streaming log for the job the agent is running against.
// The real page is in the career-agent Chrome window; this is a read-only peek.
export default function AgentLiveView({ jobId, status }) {
  const [lines, setLines] = useState([]);
  const [tick, setTick] = useState(0);
  const logRef = useRef(null);

  useEffect(() => {
    let alive = true;
    let timer;
    const poll = () => {
      fetchAgentLog(jobId, 60).then((b) => {
        if (!alive) return;
        if (b) setLines(b.lines);
        setTick((t) => t + 1);
      }).catch(() => {}).finally(() => { if (alive) timer = setTimeout(poll, 1000); });
    };
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [jobId]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines]);

  return (
    <div data-testid={`live-view-${jobId}`} style={{ margin: "6px 0 2px 14px", display: "flex", gap: 10, flexWrap: "wrap" }}>
      {status && status.screenshot && (
        <a href={status.screenshot} target="_blank" rel="noreferrer" style={{ flex: "0 0 auto" }}>
          <img src={`${status.screenshot}?t=${tick}`} alt="Live view of the page being filled"
               style={{ width: 200, maxWidth: "100%", borderRadius: 8, border: "0.5px solid var(--hairline)", display: "block" }} />
        </a>
      )}
      <pre ref={logRef} aria-label="Agent live log" style={{ ...PRE, flex: "1 1 240px", minWidth: 0 }}>
        {lines.length ? lines.join("\n") : "Waiting for log output…"}
      </pre>
    </div>
  );
}
