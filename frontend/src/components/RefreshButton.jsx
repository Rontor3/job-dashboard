import React, { useEffect, useRef, useState } from "react";
import { refreshStatus, startRefresh } from "../api.js";
import { RefreshIcon } from "./icons.jsx";

export default function RefreshButton({ onDone }) {
  const [status, setStatus] = useState({ running: false, stage: "idle" });
  const timer = useRef(null);
  const alive = useRef(true);

  const poll = () => {
    refreshStatus().then((s) => {
      if (!alive.current) return;
      setStatus(s);
      if (s.running) timer.current = setTimeout(poll, 1000);
      else if (s.stage === "done" || s.stage === "error") onDone(s);
    });
  };

  useEffect(() => () => {
    alive.current = false;
    clearTimeout(timer.current);
  }, []);

  const click = () =>
    startRefresh()
      .then(() => poll())
      .catch((e) => setStatus({ running: false, stage: "error", error: String(e) }));

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      {status.stage === "error" && (
        <span role="alert" style={{ fontSize: 11, color: "var(--pastel-pink-ink)" }}>refresh failed: {status.error}</span>
      )}
      {status.last_result?.embed_skipped && (
        <span role="alert" style={{ fontSize: 11, background: "var(--pastel-peach)", color: "var(--pastel-peach-ink)", borderRadius: 8, padding: "3px 8px" }}>
          scoring skipped: {status.last_result.embed_skipped}
        </span>
      )}
      <button
        onClick={click}
        disabled={status.running}
        style={{ border: "none", cursor: status.running ? "wait" : "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 6, background: "var(--paper)", borderRadius: "var(--radius-pill)", padding: "7px 16px", color: "var(--pastel-lavender-ink)" }}
      >
        <RefreshIcon spinning={status.running} />
        {status.running ? status.stage : "Refresh"}
      </button>
    </span>
  );
}
