"""What does a long-answer question need? One model call lists the needs (from a fixed set) and picks a project;
a regex planner is the fallback and the eval baseline. Output is always validated against the allowed ids."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

NEEDS = ("intro", "one_project", "projects_overview", "why_company", "why_role", "looking_for", "challenge",
         "working_style", "skills_list", "other")
PROJECT_NEEDS = {"one_project", "challenge", "why_company", "why_role"}
MAX_NEEDS = 3


@dataclass(frozen=True)
class Plan:
    needs: tuple[str, ...]
    project_id: str | None = None
    reason: str = ""
    source: str = "model"              # model | heuristic | prior


# order matters: it is the order needs are reported in
_HEURISTICS = [
    ("intro", r"about yourself|about you\b|introduce yourself|tell us about you"),
    ("one_project", r"proud of|proudest|most proud|(a|one|your|favou?rite|challenging) project|project (you|that you)"),
    ("projects_overview", r"(list|key|main|notable) projects"),
    ("why_company", r"why (do you want to )?(join|work (at|for|with)|us\b|this company)|interests? you|"
                    r"interested in (us|this company|working)|what interests"),
    ("why_role", r"why (this|the) (role|position|job)"),
    ("looking_for", r"looking for|next role|career goals?"),
    ("challenge", r"challeng|difficult|problem you (solved|faced)|hardest"),
    ("working_style", r"how do you (like to )?work|working style|ownership"),
    ("skills_list", r"skill ?set|list (down )?(your )?skills|technical skills|tech stack"),
]
_COMPILED = [(need, re.compile(rx, re.I)) for need, rx in _HEURISTICS]


def heuristic_needs(question: str) -> tuple[str, ...]:
    found = [need for need, rx in _COMPILED if rx.search(question or "")]
    return tuple(found[:MAX_NEEDS]) or ("other",)


def build_plan_prompt(question, jd, kb) -> str:
    projects = "\n".join(f"- {c.project_id}: {c.text}" for c in kb.list_projects())
    return (
        "A job application asks one free-text question. Decide what material is needed to answer it.\n\n"
        f'QUESTION: "{question}"\n\nJOB (excerpt): {(jd or "")[:1200]}\n\nCANDIDATE PROJECTS:\n{projects}\n\n'
        f"Allowed needs (choose 1-{MAX_NEEDS}): {', '.join(NEEDS)}.\n"
        "intro = about the candidate; one_project = a specific project in depth; projects_overview = several projects; "
        "why_company / why_role = fit with this company / role; looking_for = goals; challenge = a hard problem solved; "
        "working_style = how they work; skills_list = skills; other = anything else.\n"
        "If a need uses a project, give the id of the ONE project that best fits the job and question.\n"
        'Reply with ONLY a JSON object: {"needs": ["..."], "project_id": "<id or null>", "reason": "<one short line>"}'
    )


def parse_plan(reply, project_ids) -> Plan | None:
    m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S), flags=re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("needs"), list):
        return None
    needs = tuple(n for n in d["needs"] if n in NEEDS)[:MAX_NEEDS]
    if not needs:
        return None
    pid = d.get("project_id") if d.get("project_id") in project_ids else None
    reason = d.get("reason") if isinstance(d.get("reason"), str) else ""
    return Plan(needs, pid, reason, "model")


def plan_needs(question, jd, kb, llm=None, prior_project=None) -> Plan:
    ids = {u["id"] for u in kb.projects()}
    plan = None
    if llm is not None:
        try:
            plan = parse_plan(llm(build_plan_prompt(question, jd, kb)), ids)
        except Exception:
            plan = None
    if plan is None:
        plan = Plan(heuristic_needs(question), None, "", "heuristic")
    pid, source = plan.project_id, plan.source
    if prior_project in ids:
        pid, source = prior_project, "prior"
    if pid is None and set(plan.needs) & PROJECT_NEEDS:
        ranked = kb.rank_projects(f"{question} {jd}")
        pid = ranked[0][0] if ranked else None
    return Plan(plan.needs, pid, plan.reason, source)
