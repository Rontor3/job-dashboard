"""Automated LLM deep-rank batch — judge every un-verdicted job for fit.

Nuisance titles are auto-marked Poor Fit (no LLM call). The rest are judged by
the local LLM (verdict + score + strengths + gaps), down-ranked by the
eligibility rule, and recorded. Idempotent: only touches jobs with no verdict.
Never raises per-job — a judging failure records a neutral Moderate Fit.
"""
from __future__ import annotations

import re

from job_dashboard.db import record_llm_evaluation
from job_dashboard.match.relevance import nuisance_match
from job_dashboard.rank_io import apply_eligibility

VERDICTS = ["Strong Fit", "Good Fit", "Moderate Fit", "Weak Fit", "Poor Fit"]
_DEFAULT_SCORE = {"Strong Fit": 85, "Good Fit": 68, "Moderate Fit": 52,
                  "Weak Fit": 38, "Poor Fit": 15}


def _build_prompt(job, profile_text):
    desc = (job.get("description") or "")[:3000]
    return (
        "You screen jobs for a candidate. Judge fit and reply EXACTLY in this "
        "format, nothing else:\n"
        "Verdict: <Strong Fit|Good Fit|Moderate Fit|Weak Fit|Poor Fit>\n"
        "Score: <0-100>\n"
        "Strengths: <short comma list>\n"
        "Gaps: <short comma list>\n\n"
        f"CANDIDATE PROFILE:\n{(profile_text or '')[:1500]}\n\n"
        f"JOB: {job.get('title')} at {job.get('company')}\n{desc}\n"
    )


def _parse(text):
    text = text or ""
    verdict = next((v for v in VERDICTS if v.lower() in text.lower()), None)
    m = re.search(r"score\D{0,5}(\d{1,3})", text, re.I)
    score = max(0, min(100, int(m.group(1)))) if m else None
    if verdict is None and score is not None:
        verdict = ("Strong Fit" if score >= 80 else "Good Fit" if score >= 62
                   else "Moderate Fit" if score >= 48 else "Weak Fit" if score >= 30
                   else "Poor Fit")
    if verdict is None:
        verdict, score = "Moderate Fit", 50
    if score is None:
        score = _DEFAULT_SCORE[verdict]

    def grab(label):
        mm = re.search(label + r"\s*:?\s*(.+)", text, re.I)
        if not mm:
            return []
        parts = re.split(r"[,;\n]", mm.group(1))
        return [p.strip(" -•\t") for p in parts if p.strip(" -•\t")][:4]

    return {"verdict": verdict, "llm_score": score,
            "strengths": grab("strengths"), "gaps": grab("gaps")}


def judge_job(job, profile_text, llm):
    try:
        out = llm(_build_prompt(job, profile_text))
        return _parse(out if isinstance(out, str) else "")
    except Exception:
        return {"verdict": "Moderate Fit", "llm_score": 50,
                "strengths": [], "gaps": ["auto: judge failed"]}


def deep_rank_unranked(conn, llm=None, profile_text=None, candidate_years=None,
                       limit=None, on_progress=None):
    if profile_text is None:
        from job_dashboard.match.profile_text import compose_profile_text
        profile_text = compose_profile_text().text
    if llm is None:
        from job_dashboard.letter.draft import make_default_llm
        llm = make_default_llm()
    if candidate_years is None:
        from job_dashboard.match.eligibility import candidate_years_from_profile
        candidate_years = candidate_years_from_profile(profile_text) or 3

    rows = conn.execute(
        """SELECT j.id, j.title, j.company, j.description
           FROM jobs j LEFT JOIN match_scores m ON m.job_id = j.id
           WHERE j.duplicate_of IS NULL AND m.verdict IS NULL
           ORDER BY m.embed_score IS NULL, m.embed_score DESC, j.id""").fetchall()
    if limit:
        rows = rows[:limit]

    counts = {"nuisance": 0, "llm": 0, "skipped": 0, "total": 0}
    for jid, title, company, desc in rows:
        job = {"id": jid, "title": title, "company": company, "description": desc}
        hit = nuisance_match(title)
        if hit:
            payload = {"verdict": "Poor Fit", "llm_score": 8, "strengths": [],
                       "gaps": [f"off-target role ({hit})"], "flags": {}}
            bucket = "nuisance"
        else:
            payload = {**judge_job(job, profile_text, llm), "flags": {}}
            bucket = "llm"
        adj = apply_eligibility(job, payload, candidate_years)
        try:
            record_llm_evaluation(conn, jid, llm_score=adj["llm_score"], verdict=adj["verdict"],
                                  strengths=adj.get("strengths", []), gaps=adj.get("gaps", []),
                                  flags=adj.get("flags", {}))
        except Exception:
            # e.g. a job never embedded yet — skip rather than abort the batch.
            counts["skipped"] += 1
            continue
        counts[bucket] += 1
        counts["total"] += 1
        if on_progress and counts["total"] % 25 == 0:
            on_progress(counts)
    conn.commit()
    return counts
