import React, { useCallback, useEffect, useState } from "react";
import { fetchMailScanStatus, startMailScan } from "../api.js";

function ago(epoch) {
  if (!epoch) return "never";
  const m = Math.round((Date.now() / 1000 - epoch) / 60);
  if (m < 2) return "just now";
  if (m < 90) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
}

// "Checks your inbox daily for replies from companies you applied to."
export default function MailBar({ onChanged }) {
  const [st, setSt] = useState(null);
  const load = useCallback(() => fetchMailScanStatus().then(setSt).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!st?.running) return undefined;
    const t = setInterval(() => { load(); }, 2000);
    return () => clearInterval(t);
  }, [st?.running, load]);
  // When a scan finishes, the tracker may have moved jobs.
  const [wasRunning, setWasRunning] = useState(false);
  useEffect(() => {
    if (wasRunning && st && !st.running && onChanged) onChanged();
    setWasRunning(!!st?.running);
  }, [st?.running]);                                     // eslint-disable-line react-hooks/exhaustive-deps

  const scan = () => startMailScan().then(() => setSt((s) => ({ ...(s || {}), running: true }))).catch(() => {});
  const res = st?.last_result;
  const note = !st ? "" : st.connected === false
    ? "Gmail isn't connected — run: python -m career_agent.integrations.gmail_otp authorize"
    : res?.error ? `Last check failed (${res.error})`
    : res ? `${res.matched} new reply(ies) in ${res.scanned} mails` : "";
  return (
    <div data-testid="mail-bar" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "10px 0 14px",
                                         fontSize: 12, color: "var(--ink-soft)" }}>
      <button onClick={scan} disabled={!st || st.running}
        style={{ fontSize: 12, padding: "4px 12px", borderRadius: "var(--radius-pill)", border: "1px solid var(--green)",
                 background: "transparent", color: "var(--green)", cursor: st?.running ? "default" : "pointer" }}>
        {st?.running ? "Checking inbox…" : "Check email"}
      </button>
      <span>Last checked {st ? ago(st.last_scan) : "…"}{note ? ` · ${note}` : ""}</span>
    </div>
  );
}
