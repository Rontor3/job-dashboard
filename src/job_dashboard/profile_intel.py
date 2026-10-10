"""How ready the user is for application forms, filling the gaps from what they've already given us, and reading what
they type the way a person would.

    readiness(conn)                  how much of what forms ask is known: percent, ready (every must-have known), gaps
    autofill(conn, sources, llm)     read the résumé (and the LinkedIn profile, the candidate profile, the essay bank)
                                     and fill every gap they answer, grounded only in that text
    interpret(conn, ..., text, llm)  a typed answer → the clean answer, other questions it also answers, and anything
                                     that is a request for the agent rather than an answer

Every write goes through the change log (Undo). The model is reached only through job_dashboard.llm; tests pass a
fake ``llm`` (prompt -> dict).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from job_dashboard import changes, qa_store

# What application forms ask, from the forms the agent has filled: a must-have is asked by nearly every form and has
# no safe default; the rest is asked often enough that knowing it saves you a question later.
@dataclass(frozen=True)
class Need:
    key: str              # "profile:<column>" | "qbank:<entry id>" | "resume"
    label: str
    required: bool = False
    why: str = ""         # for a situational need: which of your jobs ask it


NEEDS = (
    Need("resume", "Your résumé (PDF)", True),
    Need("profile:full_name", "Full name", True),
    Need("profile:email", "Email", True),
    Need("profile:phone", "Phone", True),
    Need("profile:location", "Current city", True),
    Need("profile:linkedin_url", "LinkedIn URL", True),
    Need("profile:years_experience", "Years of experience", True),
    Need("profile:notice_period", "Notice period", True),
    Need("profile:salary_expectation", "Expected salary", True),
    Need("profile:current_ctc", "Current salary", True),
    Need("qbank:current_title", "Current job title", True),
    Need("qbank:current_employer", "Current employer", True),
    Need("qbank:highest_degree", "Highest degree", True),
    Need("qbank:university", "University", True),
    Need("qbank:graduation_year", "Graduation year", True),
    Need("profile:work_authorization", "Work authorization", True),
    Need("qbank:field_of_study", "Field of study"),
    Need("qbank:degree_completed", "Degree completed"),
    Need("qbank:sponsorship_required", "Needs visa sponsorship"),
    Need("qbank:citizenship", "Citizenship"),
    Need("profile:willing_to_relocate", "Willing to relocate"),
    Need("qbank:work_arrangement", "Remote / hybrid / onsite"),
    Need("qbank:preferred_locations", "Preferred locations"),
    Need("qbank:languages_spoken", "Languages you speak"),
    Need("qbank:english_proficiency", "English proficiency"),
    Need("qbank:certifications", "Certifications"),
    Need("qbank:cloud_platforms", "Cloud platforms"),
    Need("profile:github_url", "GitHub URL"),
    Need("profile:reason_for_change", "Why you're looking"),
    Need("qbank:people_management", "Managed people"),
)
_WEIGHT = {True: 3, False: 1}
READY_AT = 85                                    # percent, with every must-have known


def needs(conn) -> list[Need]:
    """Every need, plus what only some of your jobs ask (a JLPT level for Japan, a portfolio for design roles…)."""
    from job_dashboard import situational
    fixed = {n.key for n in NEEDS}
    return [*NEEDS, *(Need(f"qbank:{a['id']}", a["label"], False, a["why"]) for a in situational.active(conn)
                      if f"qbank:{a['id']}" not in fixed)]


def _profile(conn) -> dict:
    from job_dashboard.apply.store import get_application_profile
    return get_application_profile(conn) or {}


def _has_resume() -> bool:
    from pathlib import Path
    from job_dashboard.match.profile_text import current_resume_pdf
    return Path(current_resume_pdf()).is_file()


def known(conn, all_needs: list[Need] | None = None) -> dict[str, str]:
    """{need key: value} for every need already answered."""
    from career_agent.memory import qbank
    profile = _profile(conn)
    out = {"resume": "uploaded"} if _has_resume() else {}
    for n in (all_needs if all_needs is not None else needs(conn)):
        kind, _, ref = n.key.partition(":")
        if kind == "profile":
            v = profile.get(ref)
        elif kind == "qbank":
            e = qbank.get_entry(conn, ref)
            v = None if e is None else (profile.get(e["profile_ref"]) if e.get("profile_ref") else e["answer"])
        else:
            continue
        if v is not None and str(v).strip():
            out[n.key] = str(v)
    return out


def readiness(conn) -> dict:
    every = needs(conn)
    have = known(conn, every)
    total = sum(_WEIGHT[n.required] for n in every)
    got = sum(_WEIGHT[n.required] for n in every if n.key in have)
    missing = [n for n in every if n.key not in have]
    percent = round(100 * got / total)
    must = [n for n in missing if n.required]
    return {
        "percent": percent, "ready": not must and percent >= READY_AT,
        "required_missing": [{"key": n.key, "label": n.label} for n in must],
        "optional_missing": [{"key": n.key, "label": n.label, **({"why": n.why} if n.why else {})}
                             for n in missing if not n.required],
        "known": len(have), "total": len(every),
    }


# ── Filling gaps from what the user already gave us ──────────────────────────────────────────────────────────────

def _targets(conn, keys) -> list[dict]:
    """The questions to answer, with their type and choices, for the model."""
    from career_agent.memory import qbank
    from job_dashboard import situational
    out = []
    for key in keys:
        kind, _, ref = key.partition(":")
        if kind == "qbank":
            e = qbank.get_entry(conn, ref)
            if e is None or e.get("profile_ref"):
                continue
            opts = qbank.choices(ref) or situational.options(ref)
            out.append({"id": key, "question": e["question"], "type": e["atype"], **({"choices": opts} if opts else {})})
        elif kind == "profile":
            out.append({"id": key, "question": next((n.label for n in NEEDS if n.key == key), ref), "type": "text"})
    return out


def write(conn, answers: dict[str, object]) -> list[dict]:
    """Save {need key | "qbank:<id>": value}; returns what was written. Unknown keys are ignored."""
    from career_agent.memory import qbank
    from job_dashboard.apply.store import _PROFILE_COLS
    done = []
    for key, value in answers.items():
        if value is None or not str(value).strip():
            continue
        kind, _, ref = str(key).partition(":")
        value = str(value).strip()[:500]
        if kind == "profile" and ref in _PROFILE_COLS:
            changes.apply(conn, "profile", "1", ref, value)
        elif kind == "qbank" and qbank.get_entry(conn, ref) is not None:
            e = qbank.get_entry(conn, ref)
            if e.get("profile_ref"):
                changes.apply(conn, "profile", "1", e["profile_ref"], value)
            else:
                changes.apply(conn, "qbank", ref, "answer", value)
        else:
            continue
        done.append({"key": key, "value": value})
    return done


AUTOFILL_PROMPT = """You fill in a job applicant's details from their own documents. Answer ONLY what the documents
state or make certain (e.g. a graduation date answers "Have you completed a bachelor's degree?"). Never guess
salaries, notice periods, demographics or anything not in the text. For a question with choices, answer with one
choice exactly as written. Dates as YYYY, years as a number, lists comma-separated.

Documents:
{docs}

Questions (id, question, type, choices):
{questions}

Return JSON: {{"answers": {{"<id>": "<answer>", ...}}}} with only the ids you can answer from the documents."""


def autofill(conn, docs: dict[str, str], llm) -> dict:
    """Fill every gap the documents answer. ``docs``: {source name: text}."""
    every = needs(conn)
    have = known(conn, every)
    gaps = [n.key for n in every if n.key not in have and n.key != "resume"]
    from career_agent.memory import qbank
    for e in qbank.entries(conn):                         # and whatever else forms ask that the documents answer
        key = f"qbank:{e['id']}"
        if key not in gaps and not (e["answer"] or "").strip() and not e.get("profile_ref") and e["topic"] in (
                "experience", "work_auth", "location") and not e.get("rule"):
            gaps.append(key)
    targets = _targets(conn, gaps)
    text = "\n\n".join(f"## {name}\n{body[:12000]}" for name, body in docs.items() if body and body.strip())
    if not targets or not text:
        return {"filled": [], "sources": [k for k, v in docs.items() if v]}
    out = llm(AUTOFILL_PROMPT.format(docs=text, questions=json.dumps(targets, ensure_ascii=False)))
    answers = {k: v for k, v in (out.get("answers") or {}).items() if k in {t["id"] for t in targets}}
    filled = write(conn, answers)
    qa_store.set_setting(conn, "profile_autofill_at", qa_store._now())
    return {"filled": filled, "sources": [k for k, v in docs.items() if v]}


# ── Reading a typed answer like a person would ───────────────────────────────────────────────────────────────────

INTERPRET_PROMPT = """A job applicant typed this while answering a form question for their job-application assistant.

Question: {question}{choices}
They typed: {text}

Separate what they typed into:
- "answer": the answer to the question, cleaned up and in the form a job form expects (keep their facts; drop chatter,
  questions and instructions). For choices, one choice exactly as written. null if they didn't answer it.
- "also": other questions from the list below that what they typed also answers, as {{"<id>": "<answer>"}}.
- "request": anything that is a question or an instruction for the assistant rather than an answer (e.g. "why didn't
  you read this from my LinkedIn?", "use my latest résumé"), restated in one sentence; null if none.

Other questions (id, question, type, choices):
{others}

Return JSON: {{"answer": ..., "also": {{...}}, "request": ...}}"""


def interpret(conn, question: str, text: str, llm, choices: list[str] | None = None, entry_id: str | None = None) -> dict:
    every = needs(conn)
    have = known(conn, every)
    others = [t for t in _targets(conn, [n.key for n in every if n.key not in have and n.key != "resume"])
              if t["id"] != f"qbank:{entry_id}"]
    prompt = INTERPRET_PROMPT.format(question=question, text=text.strip()[:2000], others=json.dumps(others[:40], ensure_ascii=False),
                                     choices=f"\nChoices: {', '.join(choices)}" if choices else "")
    try:
        out = llm(prompt)
    except Exception as e:                                # the model is down: keep what they typed, as typed
        return {"answer": text.strip(), "also": {}, "request": None, "interpreted": False, "error": type(e).__name__}
    ids = {t["id"] for t in others}
    answer = out.get("answer")
    return {"answer": str(answer).strip() if answer not in (None, "") else None,
            "also": {k: v for k, v in (out.get("also") or {}).items() if k in ids and v not in (None, "")},
            "request": (out.get("request") or None) and str(out["request"]).strip(),
            "interpreted": True}
