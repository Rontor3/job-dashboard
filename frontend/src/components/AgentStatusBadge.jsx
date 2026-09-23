import React, { useEffect, useRef, useState } from "react";
import { fetchApplyAgentStatus } from "../api.js";

// The real feedback is the visible career-agent Chrome window filling the
// form — this badge only exists so a second click doesn't misfire, and to
// show at a glance which job it's currently on.
export default function AgentStatusBadge() {
  const [status, setStatus] = useState(null);
  const timer = useRef(null);
  const alive = useRef(true);

  const poll = () => {
    fetchApplyAgentStatus().then((s) => {
      if (!alive.current) return;
      setStatus(s);
      if (s.running) timer.current = setTimeout(poll, 1000);
    }).catch(() => {
      if (alive.current) timer.current = setTimeout(poll, 1000);
    });
  };

  useEffect(() => {
    poll();
    return () => { alive.current = false; clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!status || !status.running) return null;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, fontSize: 12,
      background: "var(--green-tint)", color: "var(--green-mid)",
      borderRadius: 10, padding: "8px 12px", marginBottom: 12,
    }}>
      <span aria-hidden="true" style={{ width: 7, height: 7, borderRadius: "50%",
                                        background: "var(--green)", animation: "breathe 2.2s ease-in-out infinite" }} />
      <span>Agent applying to job #{status.job_id}{status.title ? ` — currently on: ${status.title}` : "…"}</span>
      {status.screenshot && (
        <a href={status.screenshot} target="_blank" rel="noreferrer"
           style={{ color: "var(--green)", marginLeft: "auto" }}>
          screenshot
        </a>
      )}
    </div>
  );
}
