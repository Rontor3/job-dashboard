import React, { useCallback, useEffect, useRef, useState } from "react";
import { addManyToQueue, addToQueue } from "../api.js";
import { useOptionalAgent } from "../agent/AgentProvider.tsx";
import { dismissNotification, fetchNotifications, readNotifications } from "../agent/client.ts";

// The Inbox's updates: what happened while you weren't looking (applications sent, runs that stopped, strong new
// matches, interview emails, the agents' own notes), newest first. Every card can be acted on right here, or handed
// to the agent, which sees the card as context and can do the rest.

const MARK = { submitted: "✓", parked: "‖", failed: "!", matches: "★", tracker: "✉", agent: "◆" };
const POLL_MS = 20_000;

export function ago(iso, now = Date.now()) {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

function Update({ n, onOpenJob, onShowJobs, onDismiss, onChange }) {
  const agent = useOptionalAgent();
  const card = useRef(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const ids = n.data?.job_ids || [];
  const act = (p, msg) => {
    setBusy(true);
    p.then((r) => { setDone(typeof msg === "function" ? msg(r) : msg); onChange?.(); })
      .catch((e) => setDone(`Couldn't: ${e.message || e}`)).finally(() => setBusy(false));
  };
  const ask = (q) => agent?.openPopover(card.current, q);
  const review = () => agent?.start(
    `Have the critic and the advocate review jobs ${ids.join(", ")} against my target job. Strike the weak ones, `
    + "tell me why in a word or two each, and propose applying to the rest.");

  return (
    <li className={`update update-${n.level}${n.read_at ? "" : " update-unread"}`} ref={card}
      data-agent={`notification:${n.id}`}>
      <span className={`update-mark update-mark-${n.kind}`} aria-hidden="true">{MARK[n.kind] || "•"}</span>
      <div className="update-main">
        <div className="update-head">
          <span className="update-title">{n.title}</span>
          <time dateTime={n.at}>{ago(n.at)}</time>
        </div>
        {n.body && <p className="update-body">{n.body}</p>}
        {done ? <p className="update-done" role="status">{done}</p> : (
          <div className="update-actions">
            {ids.length > 0 && <>
              <button className="btn btn-sm btn-primary" disabled={busy}
                onClick={() => act(addManyToQueue(ids), (r) => `Queued ${r.queued?.length ?? ids.length}. The agent is applying; questions will land here.`)}>
                Apply to {ids.length === 1 ? "it" : `all ${ids.length}`}
              </button>
              {agent && ids.length > 1 && <button className="btn btn-sm" onClick={review}>Review with the agents first</button>}
              {onShowJobs && <button className="btn btn-sm btn-quiet" onClick={() => onShowJobs(ids)}>Show them</button>}
            </>}
            {n.kind === "failed" && n.job_id && (
              <button className="btn btn-sm" disabled={busy}
                onClick={() => act(addToQueue(n.job_id, { front: true, start: true }), "Back in the queue.")}>Try again</button>
            )}
            {(n.kind === "parked" || n.kind === "failed") && agent && (
              <button className="btn btn-sm" onClick={() => ask("What do I need to do here? Do whatever you can yourself.")}>
                Ask the agent
              </button>
            )}
            {n.job_id && onOpenJob && <button className="btn btn-sm btn-quiet" onClick={() => onOpenJob(n.job_id)}>Open job</button>}
          </div>
        )}
      </div>
      <button className="icon-btn update-x" aria-label={`Dismiss ${n.title}`} onClick={() => onDismiss(n.id)}>×</button>
    </li>
  );
}

export default function Updates({ onOpenJob, onShowJobs, onUnread, onChange }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => fetchNotifications()
    .then((d) => { setItems(Array.isArray(d?.items) ? d.items : []); onUnread?.(d?.unread || 0); setError(null); })
    .catch((e) => setError(String(e.message || e))), [onUnread]);
  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {                       // seen once it's been on screen a moment
    const fresh = (items || []).filter((n) => !n.read_at).map((n) => n.id);
    if (!fresh.length) return undefined;
    const t = setTimeout(() => readNotifications(fresh).then((d) => onUnread?.(d.unread)).catch(() => {}), 2500);
    return () => clearTimeout(t);
  }, [items, onUnread]);

  const dismiss = (id) => {
    setItems((xs) => xs.filter((n) => n.id !== id));
    dismissNotification(id).then((d) => onUnread?.(d.unread)).catch(() => {});
  };

  if (error) return <div role="alert" className="alert">Updates: {error}</div>;
  if (!items) return null;
  return (
    <section aria-label="Updates" className="updates">
      <div className="updates-head">
        <h2 className="section-title">Updates</h2>
        {items.length > 1 && (
          <button className="linkish" onClick={() => { items.forEach((n) => dismissNotification(n.id).catch(() => {})); setItems([]); onUnread?.(0); }}>
            Clear all
          </button>
        )}
      </div>
      {items.length === 0
        ? <p className="view-sub">Nothing new. Applications the agents send, runs that stop and strong new matches show up here.</p>
        : (
          <ul className="update-list">
            {items.map((n) => <Update key={n.id} n={n} onOpenJob={onOpenJob} onShowJobs={onShowJobs} onDismiss={dismiss} onChange={onChange} />)}
          </ul>
        )}
    </section>
  );
}
