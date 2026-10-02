import React, { useEffect, useState } from "react";
import {
  fetchAutosubmit, moveInQueue, pauseQueue, removeFromQueue, setAutosubmit, startQueue,
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
  const [showAuto, setShowAuto] = useState(false);
  const queued = items.filter((i) => i.state === "queued").length;
  const parked = items.filter((i) => i.state === "parked").length;
  const running = !!queue?.running;

  useEffect(() => {
    if (showAuto && auto === null) fetchAutosubmit().then(setAuto).catch(() => setAuto({}));
  }, [showAuto, auto]);

  const toggle = (board) => setAutosubmit(board, !auto[board]).then(setAuto);

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
        {showAuto ? "▾" : "▸"} Auto-submit
      </button>
      {showAuto && auto && (
        <div style={{ marginTop: 4 }}>
          <p style={{ fontSize: 10, color: "var(--ink-faint)", margin: "0 0 4px" }}>
            Submits only when every answer is confident. Off = fill and leave for your review.
          </p>
          {Object.keys(auto).map((b) => (
            <label key={b} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, padding: "2px 0" }}>
              <input type="checkbox" checked={!!auto[b]} onChange={() => toggle(b)} aria-label={`Auto-submit on ${BOARD_LABEL[b] || b}`} />
              {BOARD_LABEL[b] || b}
            </label>
          ))}
        </div>
      )}
    </section>
  );
}
