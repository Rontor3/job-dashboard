import React, { useEffect, useState } from "react";
import {
  fetchAutosubmit, fetchQueueSettings, moveInQueue, pauseQueue, removeFromQueue, saveQueueSettings, saveGmailConfirmation, reconcileApplied,
  setAutosubmit, startQueue,
} from "../api.js";
import { reasonText } from "../queueReasons.js";

const BOARD_LABEL = {
  naukri: "Naukri", linkedin: "LinkedIn", indeed: "Indeed", iimjobs: "iimjobs",
  instahyre: "Instahyre", wellfound: "Wellfound", workatastartup: "YC Startups", career_site: "Company sites",
};

const STATE_STYLE = {
  queued: { color: "var(--ink-soft)", label: "" },
  running: { color: "var(--green)", label: "filling…" },
  parked: { color: "#9A6B12", label: "needs you" },
  done: { color: "var(--green-mid)", label: "applied" },
  failed: { color: "var(--dupe-ink)", label: "failed" },
};


const small = { fontSize: 11, border: "none", background: "transparent", cursor: "pointer", color: "var(--ink-faint)", padding: "0 3px" };

function Row({ item, idx, items, onChange, onOpenJob }) {
  const st = STATE_STYLE[item.state] || STATE_STYLE.queued;
  const queuedIds = items.filter((i) => i.state === "queued").map((i) => i.job_id);
  const q = queuedIds.indexOf(item.job_id);
  const up = () => onChange(moveInQueue(item.job_id, queuedIds[q - 1]));
  const down = () => onChange(moveInQueue(item.job_id, q + 2 < queuedIds.length ? queuedIds[q + 2] : null));
  return (
    <li data-testid={`queue-item-${item.job_id}`} style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 0", borderTop: idx ? "0.5px solid var(--hairline)" : "none" }}>
      <span className="meta" style={{ width: 16, color: "var(--ink-faint)" }}>{item.state === "queued" ? q + 1 : "·"}</span>
      <button onClick={() => onOpenJob && onOpenJob(item.job_id)}
        style={{ flex: 1, minWidth: 0, textAlign: "left", border: "none", background: "transparent", cursor: "pointer", padding: 0, color: "var(--ink)" }}>
        <div style={{ fontSize: 12, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {item.company || "?"} · {item.title || `job ${item.job_id}`}
        </div>
        {(st.label || item.reason) && (
          <div style={{ fontSize: 10, color: st.color }}>
            {st.label}{item.reason && item.state !== "done" ? ` — ${reasonText(item.reason)}` : ""}
          </div>
        )}
      </button>
      {item.state === "queued" && (
        <>
          <button aria-label={`Move ${item.job_id} up`} disabled={q === 0} onClick={up} style={small}>↑</button>
          <button aria-label={`Move ${item.job_id} down`} disabled={q === queuedIds.length - 1} onClick={down} style={small}>↓</button>
        </>
      )}
      {item.state !== "running" && (
        <button aria-label={`Remove ${item.job_id}`} onClick={() => onChange(removeFromQueue(item.job_id))} style={small}>✕</button>
      )}
    </li>
  );
}

export default function QueuePanel({ queue, onChange, onOpenJob }) {
  const items = queue?.items || [];
  const [auto, setAuto] = useState(null);
  const [showAuto, setShowAuto] = useState(true);
  const [wait, setWait] = useState(null);
  const [gmailCheck, setGmailCheck] = useState(null);
  const [reconciled, setReconciled] = useState("");
  const queued = items.filter((i) => i.state === "queued").length;
  const parked = items.filter((i) => i.state === "parked").length;
  const running = !!queue?.running;

  useEffect(() => {
    if (auto === null) fetchAutosubmit().then(setAuto).catch(() => setAuto({}));
    if (showAuto && wait === null) fetchQueueSettings().then((s) => { setWait(s.telegram_wait_minutes); setGmailCheck(!!s.gmail_confirmation_check); }).catch(() => { setWait(10); setGmailCheck(false); });
  }, [showAuto, auto, wait]);

  const saveWait = (v) => {
    const n = Math.max(0, Math.min(120, Number(v) || 0));
    setWait(n);
    saveQueueSettings(n).catch(() => {});
  };

  const toggle = (board) => {
    const on = !auto[board];
    if (on && !window.confirm(
      `Turn auto-submit ON for ${BOARD_LABEL[board] || board}?\n\nThe agent will SUBMIT applications there without you reviewing them, `
      + "only when every answer is confident. You can turn it off at any time.")) return;
    setAutosubmit(board, on).then(setAuto);
  };
  const onBoards = Object.keys(auto || {}).filter((b) => auto[b]).map((b) => BOARD_LABEL[b] || b);

  return (
    <section aria-label="Apply queue" style={{ background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: "var(--radius-card)", padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <strong style={{ fontSize: 13 }}>Queue <span className="meta" style={{ color: "var(--ink-faint)" }}>{queued}</span></strong>
        {running && !queue.paused ? (
          <button onClick={() => onChange(pauseQueue())}
            style={{ fontSize: 12, padding: "4px 12px", borderRadius: "var(--radius-pill)", border: "1px solid var(--green)", background: "transparent", color: "var(--green)", cursor: "pointer" }}>
            ❚❚ Pause
          </button>
        ) : (
          <button onClick={() => onChange(startQueue())} disabled={!queued}
            style={{ fontSize: 12, padding: "4px 12px", borderRadius: "var(--radius-pill)", border: "none", background: queued ? "var(--green)" : "var(--hairline)", color: "#FFFFFF", cursor: queued ? "pointer" : "default" }}>
            ▶ Start
          </button>
        )}
      </div>
      {auto && (
        <div data-testid="autosubmit-status" role="status"
          style={{ fontSize: 11, margin: "0 0 6px", padding: "3px 8px", borderRadius: "var(--radius-pill)", display: "inline-block",
                   background: onBoards.length ? "#F6E7C8" : "var(--hairline)", color: onBoards.length ? "#7A5206" : "var(--ink-soft)" }}>
          {onBoards.length ? `Auto-submit ON: ${onBoards.join(", ")}` : "Auto-submit OFF — every application waits for your review"}
        </div>
      )}
      {running && queue.paused && <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>Pausing after the current job…</div>}
      {items.length === 0 ? (
        <p style={{ fontSize: 12, color: "var(--ink-faint)", margin: "4px 0" }}>Add jobs with + Queue, then press Start.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, maxHeight: 320, overflowY: "auto" }}>
          {items.map((it, i) => (
            <Row key={it.job_id} item={it} idx={i} items={items} onChange={onChange} onOpenJob={onOpenJob} />
          ))}
        </ul>
      )}
      {parked > 0 && <div style={{ fontSize: 11, color: "#9A6B12", marginTop: 6 }}>{parked} parked — answer on the tracker, then re-queue.</div>}
      <button onClick={() => setShowAuto((s) => !s)} aria-expanded={showAuto}
        style={{ ...small, marginTop: 8, padding: 0, fontSize: 11 }}>
        {showAuto ? "▾" : "▸"} Auto-submit &amp; Telegram
      </button>
      {showAuto && wait !== null && (
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--ink-soft)", marginTop: 6 }}>
          Ask me on Telegram for
          <input type="number" min="0" max="120" value={wait} aria-label="Telegram wait minutes"
            onChange={(e) => setWait(e.target.value)} onBlur={(e) => saveWait(e.target.value)}
            style={{ width: 46, fontSize: 12, padding: "2px 4px", border: "1px solid var(--hairline)", borderRadius: 6, background: "var(--card)", color: "var(--ink)" }} />
          min before parking (0 = never ask)
        </label>
      )}
      {showAuto && gmailCheck !== null && (
        <label style={{ display: "flex", alignItems: "flex-start", gap: 6, fontSize: 11, color: "var(--ink-soft)", marginTop: 6 }}>
          <input type="checkbox" checked={gmailCheck} aria-label="Confirm submissions from Gmail"
            onChange={(e) => { setGmailCheck(e.target.checked); saveGmailConfirmation(e.target.checked).catch(() => setGmailCheck(!e.target.checked)); }} />
          <span>Confirm submissions from Gmail — looks for the "application sent / thank you for applying" email after a form is left for you.
            Reads subject, sender and date only (never the message); nothing else in your inbox.</span>
        </label>
      )}
      {showAuto && gmailCheck && (
        <div style={{ marginTop: 4, fontSize: 11 }}>
          <button onClick={() => { setReconciled("Checking…"); reconcileApplied().then((r) => setReconciled(
              `Marked ${r.matched.length} applied` + (r.ambiguous.length ? `, ${r.ambiguous.length} need you to pick the job` : "") + ` (${r.emails} emails)`))
            .catch(() => setReconciled("Could not check Gmail")); }}
            style={{ ...small, padding: "2px 8px", border: "1px solid var(--hairline)", borderRadius: "var(--radius-pill)" }}>
            Mark applied jobs from Gmail now
          </button>
          {reconciled && <span role="status" style={{ marginLeft: 6, color: "var(--ink-soft)" }}>{reconciled}</span>}
        </div>
      )}
      {showAuto && auto && (
        <div style={{ marginTop: 4 }}>
          <p style={{ fontSize: 10, color: "var(--ink-faint)", margin: "0 0 4px" }}>
            Submits only when every answer is confident. Off = fill and leave for your review.
          </p>
          {Object.keys(auto).map((b) => (
            <div key={b} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 12, padding: "3px 0" }}>
              <span>{BOARD_LABEL[b] || b}</span>
              <button role="switch" aria-checked={!!auto[b]} aria-label={`Auto-submit on ${BOARD_LABEL[b] || b}`} onClick={() => toggle(b)}
                style={{ minWidth: 46, fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: "var(--radius-pill)", cursor: "pointer",
                         border: "1px solid " + (auto[b] ? "#C99A2E" : "var(--hairline)"),
                         background: auto[b] ? "#F6E7C8" : "transparent", color: auto[b] ? "#7A5206" : "var(--ink-faint)" }}>
                {auto[b] ? "ON" : "OFF"}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
