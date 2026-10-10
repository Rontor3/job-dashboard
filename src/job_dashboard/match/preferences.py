"""What the candidate's clicks teach the ranker. Every Skip (with its reasons) and every Apply/Queue is recorded;
the learned weights re-rank the feed, hide blocked companies, and are summarised into the LLM fit-judge prompt.

Features are plain and explainable: title words, seniority words, company, location words, remote. A reason picks
which features a Skip penalises ("Location" never punishes the title), so one click teaches one thing.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone

SKIP_REASONS = {
    "role": "Wrong role",
    "seniority": "Wrong level",
    "location": "Location",
    "company": "Not this company",
    "stack": "Wrong tech",
    "other": "Not interested",
}
_SENIORITY = {"intern", "junior", "jr", "associate", "senior", "sr", "staff", "principal", "lead", "head",
              "director", "manager", "vp", "chief"}
_STOP = {"and", "or", "the", "a", "an", "of", "for", "to", "in", "at", "with", "&", "-", "i", "ii", "iii", "iv"}
_STACK = {"python", "java", "golang", "go", "rust", "scala", "react", "node", "c++", "android", "ios", "sql",
          "spark", "pytorch", "tensorflow", "llm", "genai", "nlp", "cv", "frontend", "backend", "fullstack",
          "devops", "mlops", "data", "ml", "ai", "sap", "salesforce", "embedded", "qa", "sdet"}
_MAX_EFFECT = 15        # points a fully-learned preference moves the 0-100 fit score


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS job_feedback (
        job_id INTEGER PRIMARY KEY, verdict TEXT NOT NULL, reasons TEXT, created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS preference_mute (feature TEXT PRIMARY KEY)""")


def _words(text: str | None) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9+#.]*", (text or "").lower()) if w not in _STOP and len(w) > 1]


def features(job: dict) -> dict[str, list[str]]:
    """Feature groups for a job; each value is a list of ``group:value`` keys."""
    title = _words(job.get("title"))
    loc = _words(job.get("location"))
    company = (job.get("company") or "").strip().lower()
    return {
        "role": [f"title:{w}" for w in title if w not in _SENIORITY],
        "seniority": [f"level:{w}" for w in title if w in _SENIORITY],
        "stack": [f"title:{w}" for w in title if w in _STACK],
        "location": [f"loc:{w}" for w in loc] + (["remote:yes"] if job.get("is_remote") else []),
        "company": [f"company:{company}"] if company else [],
    }


def record(conn, job_id: int, verdict: str, reasons=()) -> None:
    """verdict: 'skip' (a dismissal, with reason keys from SKIP_REASONS) or 'more' (applied / queued)."""
    if verdict not in ("skip", "more"):
        raise ValueError("verdict must be skip or more")
    bad = [r for r in reasons if r not in SKIP_REASONS and r != "applied"]
    if bad:
        raise ValueError(f"unknown reasons: {bad}")
    ensure(conn)
    conn.execute("INSERT INTO job_feedback (job_id, verdict, reasons, created_at) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(job_id) DO UPDATE SET verdict=excluded.verdict, reasons=excluded.reasons, "
                 "created_at=excluded.created_at",
                 (job_id, verdict, json.dumps(list(reasons)), datetime.now(timezone.utc).isoformat()))
    conn.commit()


def _feedback_jobs(conn):
    ensure(conn)
    return conn.execute(
        """SELECT j.title, j.company, j.location, j.is_remote, f.verdict, f.reasons
           FROM job_feedback f JOIN jobs j ON j.id = f.job_id""").fetchall()


def learn(conn) -> dict:
    """{weights: {feature: w}, blocked_companies: set}. A Skip penalises only the groups its reasons name
    (no reason = role); a 'more' rewards role + stack. Weights are counts, squashed at scoring time."""
    weights: dict[str, float] = defaultdict(float)
    blocked: set[str] = set()
    for title, company, location, remote, verdict, reasons in _feedback_jobs(conn):
        f = features({"title": title, "company": company, "location": location, "is_remote": remote})
        rs = json.loads(reasons or "[]")
        if verdict == "more":
            for k in set(f["role"] + f["stack"] + f["seniority"]):
                weights[k] += 1
            continue
        if "company" in rs and f["company"]:
            blocked.add(f["company"][0])
        groups = [r for r in rs if r in ("role", "seniority", "location", "stack")] or (["role"] if not rs or "other" in rs else [])
        for k in {k for g in groups for k in f[g]}:
            weights[k] -= 1
    muted = {r[0] for r in conn.execute("SELECT feature FROM preference_mute")}
    return {"weights": {k: v for k, v in weights.items() if v and k not in muted},
            "blocked_companies": blocked - muted}


def adjustment(job: dict, learned: dict) -> float:
    """Points (−_MAX_EFFECT.._MAX_EFFECT) the learned preferences add to this job's 0-100 score."""
    w = learned["weights"]
    keys = {k for group in features(job).values() for k in group}
    raw = sum(w.get(k, 0.0) for k in keys)
    return round(_MAX_EFFECT * math.tanh(raw / 2), 1)


def rerank(jobs: list[dict], learned: dict) -> list[dict]:
    """Drop blocked companies, add ``pref`` (points) to each job, and sort by base score + pref."""
    out = []
    for j in jobs:
        f = features(j)
        if f["company"] and f["company"][0] in learned["blocked_companies"]:
            continue
        base = j.get("llm_score") if j.get("llm_score") is not None else (j.get("embed_score") or 0) * 100
        j = {**j, "pref": adjustment(j, learned)}
        j["rank_score"] = base + j["pref"]
        out.append(j)
    return sorted(out, key=lambda j: -j["rank_score"])


def summary(learned: dict, n: int = 6) -> dict:
    """Top learned likes/dislikes for display and for the LLM fit-judge."""
    items = sorted(learned["weights"].items(), key=lambda kv: kv[1])
    label = lambda k: k.split(":", 1)[1]
    return {"likes": [{"feature": k, "label": label(k), "weight": v} for k, v in reversed(items) if v > 0][:n],
            "dislikes": [{"feature": k, "label": label(k), "weight": v} for k, v in items if v < 0][:n],
            "blocked_companies": sorted(c.split(":", 1)[1] for c in learned["blocked_companies"])}


def prompt_hint(conn) -> str:
    """One line for the LLM fit-judge: what this candidate has shown they want and don't."""
    s = summary(learn(conn))
    parts = []
    if s["likes"]:
        parts.append("prefers " + ", ".join(x["label"] for x in s["likes"]))
    if s["dislikes"]:
        parts.append("has repeatedly skipped " + ", ".join(x["label"] for x in s["dislikes"]))
    return ("CANDIDATE PREFERENCES (learned from their clicks): " + "; ".join(parts) + "\n") if parts else ""


def mute(conn, feature: str) -> None:
    """Forget one learned preference (the user removed its chip)."""
    ensure(conn)
    conn.execute("INSERT OR IGNORE INTO preference_mute (feature) VALUES (?)", (feature,))
    conn.commit()
