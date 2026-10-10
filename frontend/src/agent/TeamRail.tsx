// The Agent tab's left rail: what to hand the agents (missions), who they are (profiles), and the sessions they've
// worked in, with each council member's session under the one that asked it.
import { useEffect, useState } from "react";
import type { ProfileInfo, SessionInfo } from "@jobdash/agent-protocol";
import { useAgent } from "./AgentProvider.tsx";
import { fetchProfiles } from "./client.ts";

export const MISSIONS: { title: string; hint: string; profile?: string; message: string }[] = [
  {
    title: "Find my next jobs", hint: "Scout builds a shortlist; you approve it once", profile: "scout",
    message: "Find the best openings for my target job and give me a shortlist I can apply to in one go.",
  },
  {
    title: "What needs me?", hint: "The Inbox and blocked applications, in order",
    message: "What happened since I last checked, and what needs me? Go through the Inbox and the questions holding up "
      + "applications, answer what you can from what you know, and tell me what's left, most urgent first.",
  },
  {
    title: "Get to know me", hint: "A short interview; every answer is remembered",
    message: "Interview me about the job I'm after and how I like to work, one question at a time. Save each answer "
      + "where it belongs, and stop when you know my target role, level, locations, pay floor and what to avoid.",
  },
  {
    title: "Tear apart my résumé", hint: "Critic vs advocate, then the 3 fixes that matter",
    message: "Have the critic and the advocate review my résumé against my target job. Weigh both and tell me the three "
      + "changes that would matter most, with the exact wording to use.",
  },
];

const label = (p: string) => p[0]!.toUpperCase() + p.slice(1);

function SessionRow({ s, kids, active, open }: { s: SessionInfo; kids: SessionInfo[]; active: string | null; open: (id: string) => void }) {
  return (
    <li>
      <button className="team-session" aria-current={s.id === active ? "true" : undefined} onClick={() => open(s.id)}>
        {s.profile && <span className={`team-badge team-badge-${s.profile}`}>{label(s.profile)}</span>}
        <span className="team-session-title">{s.title}</span>
      </button>
      {kids.length > 0 && (
        <ul className="team-kids">
          {kids.map((k) => (
            <li key={k.id}>
              <button className="team-session" aria-current={k.id === active ? "true" : undefined} onClick={() => open(k.id)}>
                <span className={`team-badge team-badge-${k.profile ?? "agent"}`}>{label(k.profile ?? "agent")}</span>
                <span className="team-session-title">{k.title.replace(/^\w+: /, "")}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function TeamRail() {
  const agent = useAgent();
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [all, setAll] = useState(false);
  useEffect(() => { fetchProfiles().then((p) => setProfiles(Array.isArray(p?.profiles) ? p.profiles : [])).catch(() => {}); }, []);

  const { items, active } = agent.sessions;
  const byId = new Set(items.map((s) => s.id));
  // Council members (a child with a profile) sit under their parent; forks and clones stay top-level.
  const isMember = (s: SessionInfo) => !!s.parent && !!s.profile && byId.has(s.parent);
  const top = items.filter((s) => !isMember(s));
  const shown = all ? top : top.slice(0, 8);

  return (
    <aside className="team-rail" aria-label="Agents">
      <h2 className="team-h">Hand off</h2>
      <ul className="team-missions">
        {MISSIONS.map((m) => (
          <li key={m.title}>
            <button className="team-mission" title={m.hint} onClick={() => void agent.start(m.message, { profile: m.profile })}>
              <span className="team-mission-title">{m.title}</span>
              <span className="team-mission-go" aria-hidden="true">→</span>
            </button>
          </li>
        ))}
      </ul>

      <h2 className="team-h">Agents</h2>
      <ul className="team-profiles">
        <li>
          <button className="team-profile" onClick={() => void agent.newSession()} title="Every tool; the playbook alone">
            <span className={"team-badge team-badge-agent"}>Agent</span><span className="team-profile-text">Does anything you ask</span>
          </button>
        </li>
        {profiles.map((p) => (
          <li key={p.name}>
            <button className="team-profile" onClick={() => void agent.newSession(p.name)} title={`New session as the ${p.name}`}>
              <span className={`team-badge team-badge-${p.name}`}>{label(p.name)}</span><span className="team-profile-text">{p.description}</span>
            </button>
          </li>
        ))}
      </ul>

      <h2 className="team-h">Sessions</h2>
      <ul className="team-sessions">
        {shown.map((s) => (
          <SessionRow key={s.id} s={s} active={active} open={(id) => void agent.openSession(id)}
            kids={items.filter((k) => isMember(k) && k.parent === s.id)} />
        ))}
      </ul>
      {top.length > shown.length && <button className="linkish team-more" onClick={() => setAll(true)}>All {top.length} sessions</button>}
    </aside>
  );
}
