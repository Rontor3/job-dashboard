import React, { useCallback, useEffect, useState } from "react";
import { addToQueue, fetchInbox, fetchQueue } from "./api.js";
import AnswersTab from "./components/AnswersTab.jsx";
import Inbox from "./components/Inbox.jsx";
import JobDetail from "./components/JobDetail.jsx";
import JobsView from "./components/JobsView.jsx";
import QueueStrip from "./components/QueueStrip.jsx";
import RefreshButton from "./components/RefreshButton.jsx";
import ResumeLibrary from "./components/ResumeLibrary.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import TrackerBoard from "./components/TrackerBoard.jsx";
import HiringSignals from "./components/HiringSignals.jsx";

// Four places, each one a way to give the agent feedback:
//   Needs you — questions/guesses the agent is waiting on (answers go into its memory)
//   Jobs      — apply or skip (re-ranks the feed and the fit judge)
//   Applied   — outcomes (interview / rejected) for what was sent
//   Memory    — the answers and résumé the agent reuses
const TABS = [["inbox", "Needs you"], ["jobs", "Jobs"], ["applied", "Applied"], ["memory", "Memory"]];

function Memory() {
  const [part, setPart] = useState("answers");
  return (
    <section aria-label="Memory">
      <h1 className="view-title">Memory</h1>
      <p className="view-sub">What the agent reuses on every application. Edit anything that's wrong.</p>
      <div className="segmented" role="group" aria-label="Memory section">
        {[["answers", "Answers"], ["resume", "Résumé"]].map(([k, l]) => (
          <button key={k} aria-pressed={part === k} onClick={() => setPart(k)}>{l}</button>
        ))}
      </div>
      {part === "answers" ? <AnswersTab /> : <ResumeLibrary />}
    </section>
  );
}

function Jobs(props) {
  const [source, setSource] = useState("boards");
  return (
    <>
      <div className="segmented" role="group" aria-label="Job source">
        {[["boards", "Job boards"], ["posts", "Hiring posts"]].map(([k, l]) => (
          <button key={k} aria-pressed={source === k} onClick={() => setSource(k)}>{l}</button>
        ))}
      </div>
      {source === "boards" ? <JobsView {...props} /> : <HiringSignals onOpenJob={props.onOpen} />}
    </>
  );
}

export default function App() {
  const [tab, setTab] = useState("inbox");
  const [selectedId, setSelectedId] = useState(null);
  const [queue, setQueue] = useState({ items: [] });
  const [needs, setNeeds] = useState(null);
  const [tick, setTick] = useState(0);
  const [error, setError] = useState(null);

  const bump = useCallback(() => setTick((t) => t + 1), []);
  const loadQueue = useCallback(() => fetchQueue().then(setQueue).catch(() => {}), []);
  const loadNeeds = useCallback(() => fetchInbox()
    .then((b) => setNeeds((b.questions?.length || 0) + (b.guesses?.length || 0) + (b.bank?.length || 0)))
    .catch(() => {}), []);
  useEffect(() => { loadQueue(); loadNeeds(); }, [loadQueue, loadNeeds]);
  useEffect(() => {                    // follow the runner job by job while it works
    if (!queue.running) return undefined;
    const t = setInterval(() => { loadQueue(); loadNeeds(); bump(); }, 3000);
    return () => clearInterval(t);
  }, [queue.running, loadQueue, loadNeeds, bump]);

  const onQueueChange = (p) =>
    p.then((snap) => (snap && Array.isArray(snap.items) ? setQueue(snap) : loadQueue()))
      .then(bump)
      .catch((e) => setError(String(e)));
  const onApply = (id) => onQueueChange(addToQueue(id, { front: true, start: true }));

  return (
    <div className="app">
      <header className="topbar">
        <p className="brand">Job agent</p>
        <nav className="tabs" aria-label="Sections">
          {TABS.map(([k, label]) => (
            <button key={k} className="tab" aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>
              {label}
              {k === "inbox" && needs > 0 && <span className="count" aria-label={`${needs} waiting`}>{needs}</span>}
            </button>
          ))}
        </nav>
        <div className="topbar-actions">
          <ThemeToggle />
          <RefreshButton onDone={bump} />
        </div>
      </header>
      <QueueStrip queue={queue} onChange={onQueueChange} onOpenJob={setSelectedId} />
      {error && <div role="alert" className="alert">{error}</div>}
      <main className="view">
        {tab === "inbox" && <Inbox onCount={setNeeds} onGoJobs={() => setTab("jobs")} />}
        {tab === "jobs" && <Jobs queue={queue} onApply={onApply} onOpen={setSelectedId} refreshTick={tick} />}
        {tab === "applied" && (
          <section aria-label="Applied">
            <h1 className="view-title">Applied</h1>
            <p className="view-sub">Mark what happened. Outcomes tell the agent which applications work.</p>
            <TrackerBoard onSelect={setSelectedId} refreshTick={tick} onStatsChange={bump} onStatsPoll={() => {}}
              onRequeue={(id) => onQueueChange(addToQueue(id))} />
          </section>
        )}
        {tab === "memory" && <Memory />}
      </main>
      {selectedId && <JobDetail id={selectedId} onApply={onApply} onStatusChange={bump} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
