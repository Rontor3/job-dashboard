"""Recipes: which chunks each need pulls, in what order. A recipe is plain code on purpose — the mix is reviewable
('about yourself' always includes every project card) and testable, unlike a similarity score."""
from __future__ import annotations

from dataclasses import dataclass

from .kb import Chunk, KnowledgeBase, tokens

_JD_MAX = 1500
_FACT_KEYS = ("current_title", "current_company", "years_experience")


@dataclass
class Ctx:
    project_id: str | None = None
    question: str = ""
    jd_text: str = ""
    company_text: str = ""


def _stories(kb, *slots) -> list[Chunk]:
    return [c for c in (kb.get_story(s) for s in slots) if c]


def _project(kb, ctx, sections=None) -> list[Chunk]:
    return kb.get_project(ctx.project_id, sections) if ctx.project_id else []


def _company(ctx) -> list[Chunk]:
    if ctx.company_text.strip():
        return [Chunk("company", "company", ctx.company_text.strip())]
    return [Chunk("jd", "jd", ctx.jd_text.strip()[:_JD_MAX])] if ctx.jd_text.strip() else []


def _second_card(kb, ctx) -> list[Chunk]:
    ranked = [pid for pid, _ in kb.rank_projects(f"{ctx.question} {ctx.jd_text}") if pid != ctx.project_id]
    card = kb.card(ranked[0]) if ranked else None
    return [card] if card else []


def _intro(kb, ctx):
    return _stories(kb, "story_how_you_work", "story_looking_for") + kb.get_facts(_FACT_KEYS) + kb.list_projects()


def _why_company(kb, ctx):
    return (_stories(kb, "story_looking_for", "story_why_startups") + _company(ctx)
            + _project(kb, ctx) + _second_card(kb, ctx))


def _why_role(kb, ctx):
    jd = [Chunk("jd", "jd", ctx.jd_text.strip()[:_JD_MAX])] if ctx.jd_text.strip() else []
    return _stories(kb, "story_looking_for", "story_problems") + jd + _project(kb, ctx, ("problem", "result"))


def _skills(kb, ctx):
    chunk = kb.skills_chunk()
    return [chunk] if chunk else []


def _other(kb, ctx):
    want = tokens(ctx.question)
    ranked = [pid for pid, score in kb.rank_projects(ctx.question) if score > 0][:2]
    slots = sorted(kb.story_slots(), key=lambda s: -len(want & tokens(kb.get_story(s).text if kb.get_story(s) else "")))
    return [kb.card(pid) for pid in ranked] + _stories(kb, *slots[:2])


RECIPES = {
    "intro": _intro,
    "one_project": lambda kb, ctx: _project(kb, ctx),
    "projects_overview": lambda kb, ctx: kb.list_projects(),
    "why_company": _why_company,
    "why_role": _why_role,
    "looking_for": lambda kb, ctx: _stories(kb, "story_looking_for", "story_problems"),
    "challenge": lambda kb, ctx: _project(kb, ctx, ("hardest", "result")),
    "working_style": lambda kb, ctx: _stories(kb, "story_how_you_work"),
    "skills_list": _skills,
    "other": _other,
}


def _within_budget(chunks: list[Chunk], budget: int) -> list[Chunk]:
    kept = list(chunks)
    while len(kept) > 1 and sum(len(c.text) for c in kept) > budget:
        kept.pop()
    return kept


def retrieve(plan, kb: KnowledgeBase, *, question="", jd_text="", company_text="", budget_chars=6000) -> list[Chunk]:
    ctx = Ctx(plan.project_id, question, jd_text, company_text)
    chunks, seen = [], set()
    for need in plan.needs:
        for chunk in RECIPES[need](kb, ctx):
            if chunk is not None and chunk.id not in seen:
                seen.add(chunk.id)
                chunks.append(chunk)
    return _within_budget(chunks, budget_chars)
