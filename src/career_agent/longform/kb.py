"""Typed knowledge for long answers: résumé units, the candidate's own stories, facts. Every method here is
one of the retrieval tools; chunks carry a kind and an id so a draft can be traced to what it was built from."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SECTIONS = ("problem", "built", "tech", "hardest", "result", "improve")
_HEADING = re.compile(r"^\s*##\s*([A-Za-z ]+?)\s*$", re.M)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on", "at", "is", "are", "was", "were",
         "it", "that", "this", "you", "your", "i", "my", "we", "our", "how", "what", "why", "do", "does", "did",
         "have", "has"}
_CARD_MAX = 400


@dataclass(frozen=True)
class Chunk:
    id: str                 # card:<pid> | project:<pid>:<section> | source:<pid> | story:<slot> | fact:<key> | ...
    kind: str               # card | project_story | source | story_slot | fact | jd | company
    text: str
    project_id: str | None = None
    section: str | None = None


def tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower())) - _STOP


def split_sections(text: str) -> dict[str, str]:
    """'## problem ...' blocks keyed by section; text before the first heading, and unknown headings, go to 'body'."""
    parts = _HEADING.split(text or "")
    out: dict[str, str] = {}
    if parts[0].strip():
        out["body"] = parts[0].strip()
    for name, body in zip(parts[1::2], parts[2::2]):
        key = name.strip().lower()
        key = key if key in SECTIONS else "body"
        if body.strip():
            out[key] = (out.get(key, "") + "\n" + body.strip()).strip()
    return out


class KnowledgeBase:
    def __init__(self, units, stories=None, project_stories=None, facts=None, skills=None):
        self.units = {u["id"]: u for u in units}
        self._stories = stories or {}
        self._project_stories = project_stories or {}
        self._facts = facts or {}
        self.skills = skills or []

    @classmethod
    def load(cls, conn, ingredients_path, contact=None) -> "KnowledgeBase":
        data = json.loads(Path(ingredients_path).read_text())
        stories, project_stories = {}, {}
        for eid, ans in conn.execute("SELECT id, answer FROM qbank_entry WHERE topic='story' AND status='active' "
                                     "AND TRIM(COALESCE(answer, '')) != ''"):
            if eid.startswith("story_project_"):
                project_stories[eid[len("story_project_"):]] = ans
            else:
                stories[eid] = ans
        return cls(data.get("units", []), stories, project_stories, dict(contact or {}), data.get("skills_pool", []))

    # -- tools -----------------------------------------------------------------------------------
    def projects(self) -> list[dict]:
        return [u for u in self.units.values() if u.get("type") == "project"]

    def card(self, pid) -> Chunk | None:
        u = self.units.get(pid)
        if u is None:
            return None
        text = (f"{u.get('title', '')} ({u.get('org', '')}): {u.get('problem', '')}. Built: {u.get('approach', '')}. "
                f"Tech: {', '.join(u.get('tech', []))}. Impact: {'; '.join(u.get('impact', []))}")
        return Chunk(f"card:{pid}", "card", text[:_CARD_MAX], pid)

    def list_projects(self) -> list[Chunk]:
        return [self.card(u["id"]) for u in self.projects()]

    def get_project(self, pid, sections=None) -> list[Chunk]:
        u = self.units.get(pid)
        if u is None:
            return []
        story = split_sections(self._project_stories.get(pid, ""))
        out = [Chunk(f"project:{pid}:{name}", "project_story", story[name], pid, name)
               for name in (sections or (*SECTIONS, "body")) if name in story]
        if u.get("source"):
            out.append(Chunk(f"source:{pid}", "source", u["source"], pid))
        return out

    def story_slots(self) -> list[str]:
        return list(self._stories)

    def get_story(self, slot) -> Chunk | None:
        text = self._stories.get(slot, "")
        return Chunk(f"story:{slot}", "story_slot", text) if text.strip() else None

    def get_facts(self, keys) -> list[Chunk]:
        return [Chunk(f"fact:{k}", "fact", f"{k}: {self._facts[k]}") for k in keys if str(self._facts.get(k, "")).strip()]

    def skills_chunk(self) -> Chunk | None:
        return Chunk("skills:pool", "fact", "Skills: " + ", ".join(self.skills)) if self.skills else None

    def rank_projects(self, text: str) -> list[tuple[str, int]]:
        want = tokens(text)
        scored = []
        for u in self.projects():
            have = tokens(" ".join([u.get("title", ""), u.get("problem", ""), u.get("approach", ""),
                                    " ".join(u.get("tech", [])), " ".join(u.get("tags", []))]))
            scored.append((u["id"], len(want & have)))
        return sorted(scored, key=lambda t: (-t[1], t[0]))
