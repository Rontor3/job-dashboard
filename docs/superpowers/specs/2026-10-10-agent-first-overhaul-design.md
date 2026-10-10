# Agent-first overhaul: hand the agents the job hunt, answer only what nobody else can

Date: 2026-10-10 · Status: built from the user's brief in chat ("overhaul the UX, not just the UI")

## Problem
The tabs were a set of tools: the user still went job by job, clicked Apply thirty times, checked each run, and
re-explained themselves to every new agent session. The agent was a chat beside the app, not the way through it.

## Principles
1. **The user never has to learn a job portal.** They pick jobs (or let an agent pick), confirm once, and only the
   questions no one else can answer come back, in the dashboard, in plain words.
2. **The agents learn and remember.** Durable facts land in the right store the moment they're said; what has no
   form field goes to `about-me.md`, which every session reads. All of it is visible, editable and undoable.
3. **Several agents, each with a job, checking each other.** Profiles (Scout, Critic, Advocate, or the user's own)
   are system prompts plus tool sets; the council lets one agent get an adversarial review from others.
4. **One place for what happened.** The Inbox is questions first, then updates from every background producer,
   each actionable on the spot or handed to the agent.

## What's built
- **Agent tab (first tab):** a rail with missions (Find my next jobs → Scout; What needs me?; Get to know me; Tear
  apart my résumé → critic + advocate), the agent profiles, and sessions with council members nested under the
  session that asked. An empty session shows the missions as cards.
- **Profiles** (`docs/agent/profiles/*.md`, user overrides in `data/agent/profiles/`): frontmatter `description`,
  `tools`; body → the conversation's `instructions`. `/profile`, `POST /agent/sessions {profile}`.
- **Council** (`consult_agents`): a child session per profile, run in parallel, answers returned to the asker
  (5-minute cap per member). Children are ordinary sessions the user can open.
- **Memory across sessions:** `data/agent/about-me.md` (sections Target, Preferences, Constraints, Background,
  Working style, Other) as prompt section `about_the_user`; tools `get_about_me`, `remember`; routes
  `/api/about-me`, `/api/about-me/facts`; change-logged as file `about_me` with Undo. Memory → About you edits it
  and lists what the agent saved lately.
- **Inbox:** `notification` table (`job_dashboard/notifications.py`), written by the apply queue (sent / stopped /
  failed), the submit watcher, the mail scan (interview, offer, rejection) and Refresh (strong new matches), and by
  the agent (`notify_user`). Cards: Apply to all, Review with the agents first, Show them, Try again, Ask the agent,
  Open job, dismiss. The tab badge counts blocking questions plus unread updates.
- **Bulk apply:** `POST /api/queue/batch {job_ids, start}` (consequential: the agent needs the user's Confirm).
  Jobs: checkboxes, "Select strong fits", a sticky "Apply to N" / "Review with the agents" bar; `?ids=` lists a set
  (the Inbox's "Show them").

## Not yet
- Submitting a parked, reviewed form from the dashboard (the user still presses Submit in the agent's Chrome). It
  touches the submit gate, so it needs its own design.
- Agents working on a schedule (a Scout run after every Refresh) and a reflection pass at the end of a session.
