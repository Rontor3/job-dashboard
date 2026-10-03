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
    }).catch((e) => {
      if (alive.current) setStatus({ running: false, stage: "error", error: String(e), last_result: null });
    });
  };

  useEffect(() => {
    // A refresh started earlier (before a page reload) keeps running server-side: pick it back up.
    refreshStatus().then((s) => {
      if (!alive.current) return;
      setStatus(s);
      if (s.running) timer.current = setTimeout(poll, 1000);
    }).catch(() => {});
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, []);

  const click = () =>
    startRefresh()
      .then(() => poll())
      .catch((e) => setStatus({ running: false, stage: "error", error: String(e) }));

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      {status.stage === "error" && (
        <span role="alert" style={{ fontSize: 11, color: "var(--dupe-ink)" }}>refresh failed: {status.error}</span>
      )}
      {status.last_result?.embed_skipped && (
        <span role="alert" style={{ fontSize: 11, background: "var(--warm-tint)", color: "var(--warm-ink)", borderRadius: 8, padding: "3px 8px" }}>
          scoring skipped: {status.last_result.embed_skipped}
        </span>
      )}
      {(() => {
        // One compact chip for the whole browser stage (details on hover); only real failures get their own alert.
        const sites = status.last_result?.browser || [];
        const bad = sites.filter((b) => b.note?.startsWith("blocked") || b.note?.startsWith("error"));
        const total = sites.reduce((n, b) => n + (b.new || 0), 0);
        const detail = sites.map((b) => (b.note ? `${b.site}: ${b.note}` : `${b.site} +${b.new}`)).join("\n");
        const chip = { fontSize: 11, background: "var(--warm-tint)", color: "var(--warm-ink)", borderRadius: 8, padding: "3px 8px", whiteSpace: "nowrap" };
        return (
          <>
            {sites.length > 0 && <span role="status" title={detail} style={chip}>browser sources +{total}</span>}
            {bad.map((b) => (
              <span key={b.site} role="alert" title={b.note} style={{ ...chip, color: "var(--dupe-ink)", background: "var(--dupe-bg)" }}>
                {b.site}: {b.note.split(":")[0]}
              </span>
            ))}
          </>
        );
      })()}
      <button
        onClick={click}
        disabled={status.running}
        style={{ border: "none", cursor: status.running ? "wait" : "pointer", fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 6, background: "var(--gold)", borderRadius: "var(--radius-pill)", padding: "7px 16px", color: "var(--gold-ink)" }}
      >
        <RefreshIcon spinning={status.running} />
        {status.running ? status.stage : "Refresh"}
      </button>
    </span>
  );
}
