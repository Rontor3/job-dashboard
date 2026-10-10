// The Agent tab's left rail: what to hand the agents (missions), who they are (profiles), and the sessions they've
// worked in, with each council member's session under the one that asked it.
import { useEffect, useState } from "react";
import type { ProfileInfo, SessionInfo } from "@jobdash/agent-protocol";
import { useAgent } from "./AgentProvider.tsx";
import { fetchProfiles } from "./client.ts";
import Tip from "./Tip.tsx";

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

const POWER = {
  read: "Reads only. It reviews and reports; it never changes your data.",
  write: "Can change your data. Every change shows an Undo.",
  act: "Can change your data and propose applying. Nothing is sent without your Confirm.",
};
const tool = (t: string) => t.replace(/_/g, " ");

function ProfileTip({ name, description, power, tools }: { name: string; description: string; power?: keyof typeof POWER; tools?: string[] }) {
  return (
    <div className="tip-body">
      <strong>{label(name)}</strong>
      <p>{description}</p>
      {power && <p className="tip-dim">{POWER[power]}</p>}
      <p className="tip-dim">{tools?.length ? `Uses: ${tools.slice(0, 12).map(tool).join(", ")}${tools.length > 12 ? "…" : ""}` : "Uses every tool the app has."}</p>
      <p className="tip-hint">Click to start a session as the {name}.</p>
    </div>
  );
}

function SessionTip({ s }: { s: SessionInfo }) {
  return (
    <div className="tip-body">
      <strong>{s.title}</strong>
      <p className="tip-dim">{s.profile ? `${label(s.profile)} · ` : ""}{new Date(s.createdAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p>
    </div>
  );
}

function SessionRow({ s, kids, active, open }: { s: SessionInfo; kids: SessionInfo[]; active: string | null; open: (id: string) => void }) {
  return (
    <li>
      <Tip content={<SessionTip s={s} />}>
        <button className="team-session" aria-current={s.id === active ? "true" : undefined} onClick={() => open(s.id)}>
          {s.profile && <span className={`team-badge team-badge-${s.profile}`}>{label(s.profile)}</span>}
          <span className="team-session-title">{s.title}</span>
        </button>
      </Tip>
      {kids.length > 0 && (
        <ul className="team-kids">
          {kids.map((k) => (
            <li key={k.id}>
              <Tip content={<SessionTip s={k} />}>
                <button className="team-session" aria-current={k.id === active ? "true" : undefined} onClick={() => open(k.id)}>
                  <span className={`team-badge team-badge-${k.profile ?? "agent"}`}>{label(k.profile ?? "agent")}</span>
                  <span className="team-session-title">{k.title.replace(/^\w+: /, "")}</span>
                </button>
              </Tip>
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
            <button className="team-mission" onClick={() => void agent.start(m.message, { profile: m.profile })}>
              <span className="team-mission-title">{m.title}<small>{m.hint}</small></span>
              <span className="team-mission-go" aria-hidden="true">→</span>
            </button>
          </li>
        ))}
      </ul>

      <h2 className="team-h">Agents</h2>
      <ul className="team-profiles">
        <li>
          <Tip content={<ProfileTip name="agent" description="Your general assistant: sets up the app, answers questions, changes your profile and answers, and hands work to the others." power="act" />}>
            <button className="team-profile" onClick={() => void agent.newSession()}>
              <span className={"team-badge team-badge-agent"}>Agent</span><span className="team-profile-text">Does anything you ask</span>
            </button>
          </Tip>
        </li>
        {profiles.map((p) => (
          <li key={p.name}>
            <Tip content={<ProfileTip {...p} />}>
              <button className="team-profile" onClick={() => void agent.newSession(p.name)}>
                <span className={`team-badge team-badge-${p.name}`}>{label(p.name)}</span><span className="team-profile-text">{p.description}</span>
              </button>
            </Tip>
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
