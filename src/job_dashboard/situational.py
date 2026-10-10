"""Questions only some of your jobs ask: a JLPT level for openings in Japan, a CEFR level for German or French roles,
an IELTS / TOEFL score, publications for research roles, a portfolio for design roles, a clearance, a driving licence.

A situation is active when at least one of your jobs (a good match, or one you're applying to) triggers it. Active
situations join the readiness needs (profile_intel) and the Inbox, each saying which jobs asked, and get a
question-bank entry (with its wording embedded) so the apply agent answers the form from it.

    active(conn) -> [{id, label, question, atype, options, jobs, companies, why}]
    ensure_entries(conn, embed)        create the bank entries for active situations (once)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CEFR = ["Native", "C2 (proficient)", "C1 (advanced)", "B2 (upper intermediate)", "B1 (intermediate)",
        "A2 (elementary)", "A1 (beginner)", "None"]
MIN_SCORE = 55                                    # a job counts once it's at least a fair match


def _speaks(lang: str) -> str:
    """A posting that asks for the language itself, not one that only mentions the country."""
    return (rf"(?:fluen\w*|proficien\w*|business[- ]level|native|speak\w*|written|spoken)\W+(?:\w+\W+){{0,3}}{lang}\b"
            rf"|\b{lang}\W+(?:language|speaking|speaker|fluency|skills|proficiency|is a must|required|\(\w\d)")


@dataclass(frozen=True)
class Situation:
    id: str                                       # qbank entry id (an existing seed entry, or created here)
    label: str
    question: str
    atype: str
    trigger: str                                  # regex over the job's title and description (or title only)
    why: tuple[str, str]                          # "1 of your jobs {singular}" / "3 of your jobs {plural}"
    options: tuple[str, ...] = ()
    title_only: bool = False
    place: str = ""                               # regex over the job's location: being there is enough (not one of many)
    hint: tuple[str, ...] = ()                    # words the text must contain before the (slower) trigger runs
    topic: str = "experience"
    wordings: tuple[str, ...] = field(default=())


SITUATIONS = (
    Situation("jlpt_level", "Japanese (JLPT)", "What is your Japanese proficiency (JLPT level)?", "choice",
              _speaks("japanese") + r"|\bjlpt\b", ("is in Japan or asks for Japanese", "are in Japan or ask for Japanese"),
              ("N1", "N2", "N3", "N4", "N5", "No JLPT, but I speak some Japanese", "None"),
              place=r"japan|tokyo|osaka|kyoto|yokohama|fukuoka", hint=("japanese", "jlpt"),
              wordings=("JLPT level", "Japanese language ability", "Do you speak Japanese?")),
    Situation("german_level", "German level", "What is your German language level?", "choice",
              _speaks("german") + r"|\bdeutschkenntnisse", ("is in Germany or asks for German", "are in Germany or ask for German"),
              tuple(CEFR), hint=("german", "deutsch"), place=r"german|deutschland|berlin|munich|münchen|hamburg|frankfurt|cologne|köln|stuttgart",
              wordings=("German proficiency (CEFR)", "Do you speak German?")),
    Situation("french_level", "French level", "What is your French language level?", "choice",
              _speaks("french"), ("is in France or asks for French", "are in France or ask for French"),
              tuple(CEFR), hint=("french",), place=r"france|paris|lyon|montr[ée]al|qu[ée]bec",
              wordings=("French proficiency (CEFR)", "Do you speak French?")),
    Situation("english_test_score", "IELTS / TOEFL score",
              "Do you have an English test score (IELTS, TOEFL or PTE)? Which test, score and year?", "text",
              r"\bielts\b|\btoefl\b|\bpte\b", ("asks for an English test score", "ask for an English test score"),
              wordings=("IELTS score", "TOEFL score", "English language test result")),
    Situation("publications", "Publications & results",
              "Any publications, patents or competition results (e.g. Kaggle) worth listing?", "text",
              r"research|scientist|\bphd\b", ("is a research or scientist role", "are research or scientist roles"), title_only=True,
              wordings=("List your publications", "Patents or papers", "Kaggle or competition results")),
    Situation("portfolio_url", "Portfolio", "Do you have a portfolio or personal website?", "text",
              r"design|\bux\b|\bui\b|creative|illustrat", ("is a design role", "are design roles"), title_only=True, topic="misc"),
    Situation("security_clearance", "Security clearance", "Do you hold an active government security clearance?",
              "bool", r"security clearance|\bts/sci\b|\bclearance required", ("asks about a security clearance", "ask about a security clearance"),
              topic="work_auth"),
    Situation("driving_licence", "Driving licence", "Do you hold a valid driving licence?", "bool",
              r"driv(?:ing|er'?s) licen[cs]e|own vehicle|field sales", ("asks for a driving licence", "ask for a driving licence"),
              topic="misc", wordings=("Do you have a driver's license?", "Valid driving license")),
)
BY_ID = {s.id: s for s in SITUATIONS}


def _jobs(conn) -> list[tuple]:
    """(title, company, location, text) of your live jobs: a fair match or one you've acted on."""
    try:
        return conn.execute(
            """SELECT j.title, j.company, coalesce(j.location,''), j.title || ' ' || j.description
               FROM jobs j LEFT JOIN match_scores m ON m.job_id = j.id
               WHERE j.expired = 0 AND j.duplicate_of IS NULL AND coalesce(j.status,'') NOT IN ('rejected','skipped')
                 AND (coalesce(m.llm_score, m.embed_score * 100, 0) >= ? OR j.status IS NOT NULL
                      OR j.id IN (SELECT job_id FROM apply_queue))""", (MIN_SCORE,)).fetchall()
    except Exception:                                # noqa: BLE001 — no jobs table yet
        return []


_cache: dict = {}


def _fingerprint(conn):
    try:
        return conn.execute("""SELECT (SELECT count(*) || max(fetched_at) || max(coalesce(status_updated_at,'')) FROM jobs),
                                      (SELECT max(scored_at) || max(coalesce(llm_scored_at,'')) FROM match_scores),
                                      (SELECT count(*) FROM apply_queue)""").fetchone() + (
            conn.execute("PRAGMA database_list").fetchone()[2],)
    except Exception:                                # noqa: BLE001
        return None


def _matches(s: Situation, title: str, loc: str, text: str) -> bool:
    if s.place and loc.count(",") < 3 and re.search(s.place, loc, re.I):
        return True
    body = title if s.title_only else text
    if s.hint and not any(h in body.lower() for h in s.hint):
        return False
    return bool(re.search(s.trigger, body, re.I))


def active(conn) -> list[dict]:
    """Situations your jobs trigger; recomputed only when jobs, scores or the queue change."""
    key = _fingerprint(conn)
    if key is not None and _cache.get("key") == key:
        return _cache["value"]
    jobs = _jobs(conn)
    out = []
    for s in SITUATIONS:
        hit = [(t, c) for t, c, loc, text in jobs if _matches(s, t, loc, text)]
        if not hit:
            continue
        companies = list(dict.fromkeys(c for _, c in hit if c))
        n = len(hit)
        out.append({"id": s.id, "label": s.label, "question": s.question, "atype": s.atype, "options": list(s.options),
                    "jobs": n, "companies": companies[:3],
                    "why": f"{n} of your jobs {s.why[n != 1]}" + (f" ({', '.join(companies[:3])})" if companies else "") + "."})
    if key is not None:
        _cache.update(key=key, value=out)
    return out


def ensure_entries(conn, embed) -> None:
    """Give each active situation a bank entry, embedded so form wordings match it."""
    from career_agent.memory import qbank
    for a in active(conn):
        if qbank.get_entry(conn, a["id"]) is not None:
            continue
        s = BY_ID[a["id"]]
        qbank.upsert_entry(conn, {"id": s.id, "question": s.question, "topic": s.topic, "atype": s.atype})
        texts = [s.question, *s.wordings]
        for t, v in zip(texts, embed(texts)):
            qbank.add_wording(conn, t, s.id, v, "seed")


def options(entry_id: str) -> list[str]:
    s = BY_ID.get(entry_id)
    return list(s.options) if s else []
