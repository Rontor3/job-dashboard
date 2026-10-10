import React, { useCallback, useEffect, useState } from "react";
import { addToQueue, fetchInbox, fetchQueue } from "./api.js";
import AboutMe from "./components/AboutMe.jsx";
import Updates from "./components/Updates.jsx";
import ProfileReadiness from "./components/ProfileReadiness.jsx";
import AnswersTab, { Tuning } from "./components/AnswersTab.jsx";
import IngredientsPanel from "./components/IngredientsPanel.jsx";
import Inbox from "./components/Inbox.jsx";
import JobDetail from "./components/JobDetail.jsx";
import JobsView from "./components/JobsView.jsx";
import QueueStrip from "./components/QueueStrip.jsx";
import RefreshButton from "./components/RefreshButton.jsx";
import ResumeLibrary from "./components/ResumeLibrary.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import TrackerBoard from "./components/TrackerBoard.jsx";
import HiringSignals from "./components/HiringSignals.jsx";
import { AgentProvider } from "./agent/AgentProvider.tsx";
import { fetchNotifications } from "./agent/client.ts";
import AgentTab from "./agent/AgentTab.tsx";
import { CursorButton, CursorOverlay } from "./agent/Cursor.tsx";
import Popover from "./agent/Popover.tsx";
import SetupBanner from "./agent/SetupBanner.tsx";

// Agent first. You hand the agents work and they come back only for what nobody else can answer:
//   Agent        — talk to the agents, or hand off a mission (find jobs, review my résumé, what needs me?)
//   Inbox        — questions holding up applications, then everything that happened (sent, stopped, new matches)
//   Jobs         — tick as many as you like, apply to all of them at once (= more like this); skip (= less)
//   Applications — outcomes (interview / rejected) for what was sent
//   Memory       — what the agents know about you and reuse on every form, and how they're tuned
const TABS = [["agent", "Agent"], ["inbox", "Inbox"], ["jobs", "Jobs"], ["applied", "Applications"], ["memory", "Memory"]];
const MEMORY_PARTS = [["about", "About you"], ["answers", "Answers"], ["story", "Your story"], ["resume", "Résumé"], ["tuning", "Tuning"]];

// The open tab (and Memory's section) live in the URL hash, so a reload, a bookmark or Back lands where you were.
const TAB_KEYS = TABS.map(([k]) => k);
const readHash = () => window.location.hash.replace(/^#\/?/, "").split("/");

function useHashTab() {
  const [tab, set] = useState(() => (TAB_KEYS.includes(readHash()[0]) ? readHash()[0] : "agent"));
  useEffect(() => {
    const on = () => { const t = readHash()[0]; if (TAB_KEYS.includes(t)) set(t); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const setTab = useCallback((t) => {
    set(t);
    if (readHash()[0] !== t) window.history.pushState(null, "", `#${t}`);
  }, []);
  return [tab, setTab];
}

function Memory() {
  const [part, setPartState] = useState(() => {
    const p = readHash()[1];
    return MEMORY_PARTS.some(([k]) => k === p) ? p : "about";
  });
  const setPart = (p) => { setPartState(p); window.history.replaceState(null, "", `#memory/${p}`); };
  return (
    <section aria-label="Memory">
      <h1 className="view-title">Memory</h1>
      <p className="view-sub">What the agents know about you and reuse on every application. Edit anything that's wrong.</p>
      <div className="segmented" role="group" aria-label="Memory section">
        {MEMORY_PARTS.map(([k, l]) => <button key={k} aria-pressed={part === k} onClick={() => setPart(k)}>{l}</button>)}
      </div>
      {part === "about" && <AboutMe />}
      {part === "answers" && <AnswersTab />}
      {part === "story" && (
        <>
          <p className="view-sub">Used to write essays and free-text answers.</p>
          <AnswersTab only="story" />
          <IngredientsPanel />
        </>
      )}
      {part === "resume" && <ResumeLibrary />}
      {part === "tuning" && <Tuning />}
    </section>
  );
}

function InboxPage({ onNeeds, onUnread, onGoJobs, onOpenJob, onShowJobs, onChange }) {
  const [tick, setTick] = useState(0);
  const [inboxKey, setInboxKey] = useState(0);
  return (
    <section aria-label="Inbox" className="inbox-page">
      <h1 className="view-title">Inbox</h1>
      <p className="view-sub">Only what the agents can't do without you, then everything they did.</p>
      <ProfileReadiness tick={tick} onChange={() => setInboxKey((k) => k + 1)} />
      <Inbox key={inboxKey} embedded onCount={onNeeds} onGoJobs={onGoJobs} onSubmitted={() => setTick((t) => t + 1)} />
      <Updates onOpenJob={onOpenJob} onShowJobs={onShowJobs} onUnread={onUnread} onChange={onChange} />
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
  const [tab, setTab] = useHashTab();
  const [unread, setUnread] = useState(0);
  const [focusJobs, setFocusJobs] = useState(null);
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
  const loadUnread = useCallback(() => fetchNotifications().then((d) => setUnread(d?.unread || 0)).catch(() => {}), []);
  useEffect(() => { loadQueue(); loadNeeds(); loadUnread(); }, [loadQueue, loadNeeds, loadUnread]);
  useEffect(() => {                    // the Inbox badge stays current on every tab
    const t = setInterval(() => { loadNeeds(); loadUnread(); }, 30_000);
    return () => clearInterval(t);
  }, [loadNeeds, loadUnread]);
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
    <AgentProvider tab={tab} onOpenTab={() => setTab("agent")}>
    <div className="app">
      <header className="topbar">
        <p className="brand">
          <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden="true">
            <rect width="24" height="24" rx="7" />
            <path d="M7 15.5l4-4 2.5 2.5L17.5 9" />
            <circle cx="17.5" cy="9" r="1.6" />
          </svg>
          Job agent
        </p>
        <nav className="tabs" aria-label="Sections">
          {TABS.map(([k, label]) => (
            <button key={k} className="tab" aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>
              {label}
              {k === "inbox" && (needs || 0) + unread > 0 && (
                <span className={needs ? "count" : "count count-quiet"} aria-label={`${needs || 0} waiting, ${unread} new`}>{(needs || 0) + unread}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="topbar-actions">
          <CursorButton />
          <ThemeToggle />
          <RefreshButton onDone={bump} />
        </div>
      </header>
      <SetupBanner />
      {queue.worker === false && (
        <div className="alert" role="status">The background worker isn't running, so the apply queue won't move. Restart the app.</div>
      )}
      <QueueStrip queue={queue} onChange={onQueueChange} onOpenJob={setSelectedId} />
      {error && <div role="alert" className="alert">{error}</div>}
      <main className={tab === "agent" ? "view view-agent" : "view"}>
        {tab === "inbox" && (
          <InboxPage onNeeds={setNeeds} onUnread={setUnread} onGoJobs={() => setTab("jobs")} onOpenJob={setSelectedId}
            onShowJobs={(ids) => { setFocusJobs(ids); setTab("jobs"); }} onChange={() => { loadQueue(); bump(); }} />
        )}
        {tab === "jobs" && <Jobs queue={queue} onApply={onApply} onOpen={setSelectedId} refreshTick={tick}
          focusIds={focusJobs} onClearFocus={() => setFocusJobs(null)} onQueued={(snap) => setQueue(snap)} />}
        {tab === "applied" && (
          <section aria-label="Applied">
            <h1 className="view-title">Applied</h1>
            <p className="view-sub">Mark what happened. Outcomes tell the agent which applications work.</p>
            <TrackerBoard onSelect={setSelectedId} refreshTick={tick} onStatsChange={bump} onStatsPoll={() => {}}
              onRequeue={(id) => onQueueChange(addToQueue(id))} />
          </section>
        )}
        {tab === "memory" && <Memory />}
        {tab === "agent" && <AgentTab onGo={setTab} />}
      </main>
      {selectedId && <JobDetail id={selectedId} onApply={onApply} onStatusChange={bump} onClose={() => setSelectedId(null)} />}
      <CursorOverlay />
      <Popover />
    </div>
    </AgentProvider>
  );
}
