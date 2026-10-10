// The Agent tab: the active session's conversation, past sessions to reopen, New session, and Stop.
import { useAgent } from "./AgentProvider.tsx";
import { Composer, Thread } from "./Thread.tsx";

export default function AgentTab() {
  const agent = useAgent();
  const { sessions, thread } = agent;
  const empty = thread.entries.length === 0 && !thread.running;
  return (
    <section aria-label="Agent" className="agent-tab">
      <aside className="agent-sessions" aria-label="Sessions">
        <button className="btn btn-primary" onClick={() => void agent.newSession()}>New session</button>
        <ul>
          {sessions.items.map((s) => (
            <li key={s.id}>
              <button className="agent-session" aria-current={s.id === sessions.active ? "true" : undefined}
                onClick={() => void agent.openSession(s.id)}>
                <span>{s.title}</span>
                <small>{new Date(s.createdAt).toLocaleDateString()}</small>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <div className="agent-main">
        <h1 className="view-title">Agent</h1>
        <p className="view-sub">Ask it to change your profile, answers or settings, or point at anything with the cursor (top right).</p>
        {empty && (
          <div className="agent-empty">
            {["Finish setting up the app with me", "What is the apply agent waiting on?", "Fill in my profile from my résumé"].map((q) => (
              <button key={q} className="chip" onClick={() => void agent.ask(q)}>{q}</button>
            ))}
          </div>
        )}
        <Thread entries={thread.entries} partial={thread.partial} running={thread.running}
          toolsRunning={thread.toolsRunning} focus={agent.focusEntry} />
        {thread.failure && <div role="alert" className="alert">The agent hit a problem: {thread.failure}</div>}
        {agent.error && <div role="alert" className="alert">{agent.error}</div>}
        <div className="agent-bar">
          {thread.running && (
            <>
              <span className="agent-busy">Working{thread.inbox.length ? ` · ${thread.inbox.length} queued` : ""}</span>
              <button className="btn" onClick={() => void agent.stop()}>Stop</button>
            </>
          )}
        </div>
        <Composer placeholder="Ask the agent…" onSend={(t) => void agent.ask(t)} />
      </div>
    </section>
  );
}
