import React, { useState } from "react";
import { pauseQueue, startQueue } from "../api.js";
import QueuePanel from "./QueuePanel.jsx";

// One line while the agent works (or has work waiting); the full queue and autonomy settings open on demand.
export default function QueueStrip({ queue, onChange, onOpenJob }) {
  const [open, setOpen] = useState(false);
  const items = queue?.items || [];
  const waiting = items.filter((i) => i.state === "queued").length;
  const current = items.find((i) => i.state === "running");
  if (!items.length) return null;
  const text = current ? `Applying to ${current.company || "a job"}${waiting ? ` · ${waiting} waiting` : ""}`
    : queue.paused ? `Paused · ${waiting} waiting` : waiting ? `${waiting} waiting to apply` : "Queue idle";
  return (
    <>
      <div className="strip" role="status">
        {current && <span className="pulse" aria-hidden="true" />}
        <span>{text}</span>
        <span className="spacer" />
        {queue.running
          ? <button className="btn btn-sm btn-quiet" onClick={() => onChange(pauseQueue())}>Pause</button>
          : waiting > 0 && <button className="btn btn-sm btn-quiet" onClick={() => onChange(startQueue())}>Start</button>}
        <button className="btn btn-sm btn-quiet" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Manage"}
        </button>
      </div>
      {open && <div style={{ marginTop: 10 }}><QueuePanel queue={queue} onChange={onChange} onOpenJob={onOpenJob} /></div>}
    </>
  );
}
