// What an empty session shows: the missions to hand off, and where things stand right now (what's waiting on you,
// what the agents did lately, the apply queue), so the first screen is a status board, not a blank page.
import { useEffect, useState } from "react";
import type { NotificationItem } from "@jobdash/agent-protocol";
import { useAgent } from "./AgentProvider.tsx";
import { fetchNotifications } from "./client.ts";
import { MISSIONS } from "./TeamRail.tsx";

interface Status {
  questions: number;
  toTeach: number;
  updates: NotificationItem[];
  unread: number;
  queued: number;
  running: boolean;
}

const getJson = (url: string) => fetch(url).then((r) => (r.ok ? r.json() : {}));

function useStatus(): Status | null {
  const [s, setS] = useState<Status | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all([
      getJson("/api/inbox").catch(() => ({})),
      fetchNotifications().catch(() => ({ items: [], unread: 0 })),
      getJson("/api/queue").catch(() => ({ items: [] })),
    ]).then(([box, notes, queue]: any[]) => {
      if (!live) return;
      const items = Array.isArray(queue?.items) ? queue.items : [];
      setS({
        questions: box?.questions?.length ?? 0,
        toTeach: (box?.guesses?.length ?? 0) + (box?.bank?.length ?? 0),
        updates: (Array.isArray(notes?.items) ? notes.items : []).slice(0, 4),
        unread: notes?.unread ?? 0,
        queued: items.filter((i: { state: string }) => i.state === "queued" || i.state === "running").length,
        running: !!queue?.running,
      });
    });
    return () => { live = false; };
  }, []);
  return s;
}

export default function StartScreen({ onGo }: { onGo?: (tab: string) => void }) {
  const agent = useAgent();
  const s = useStatus();
  const waiting = s ? s.questions + s.toTeach : 0;
  return (
    <div className="agent-start">
      <h2>What should the agents do?</h2>
      <p>Type anything below, or hand off one of these. You'll only be asked what nobody else can answer.</p>
      <div className="agent-start-grid">
        {MISSIONS.map((m) => (
          <button key={m.title} className="agent-start-card" onClick={() => void agent.start(m.message, { profile: m.profile })}>
            <strong>{m.title}</strong><span>{m.hint}</span>
          </button>
        ))}
      </div>

      {s && (
        <section className="agent-now" aria-label="Right now">
          <h3>Right now</h3>
          <div className="agent-now-grid">
            <button className={`agent-stat${waiting ? " agent-stat-warm" : ""}`} onClick={() => onGo?.("inbox")}>
              <span className="agent-stat-n">{waiting}</span>
              <span className="agent-stat-l">{s.questions ? `${s.questions} holding up applications` : "waiting on you"}</span>
            </button>
            <button className="agent-stat" onClick={() => onGo?.("jobs")}>
              <span className="agent-stat-n">{s.queued}</span>
              <span className="agent-stat-l">{s.running ? "applying now" : "in the apply queue"}</span>
            </button>
            <button className="agent-stat" onClick={() => onGo?.("inbox")}>
              <span className="agent-stat-n">{s.unread}</span>
              <span className="agent-stat-l">new updates</span>
            </button>
          </div>
          {s.updates.length > 0 ? (
            <ul className="agent-now-list">
              {s.updates.map((n) => (
                <li key={n.id} className={`agent-now-item agent-now-${n.level}`}>
                  <span>{n.title}</span>
                  <time dateTime={n.at}>{new Date(n.at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</time>
                </li>
              ))}
            </ul>
          ) : (
            <p className="agent-now-empty">No updates yet. When the agents apply, hit a snag or find strong matches, it shows up here and in the Inbox.</p>
          )}
          {waiting > 0 && (
            <button className="btn btn-primary btn-sm" onClick={() => onGo?.("inbox")}>
              Answer {waiting === 1 ? "it" : `the ${waiting}`} now
            </button>
          )}
        </section>
      )}
    </div>
  );
}
