"""Live check: one dry-run application per channel, answers graded for relevance, one HTML report.

    PYTHONPATH=src python3 scripts/live_check.py                      # 6 default channels
    PYTHONPATH=src python3 scripts/live_check.py --channels indeed,greenhouse --per 1
    PYTHONPATH=src python3 scripts/live_check.py --jobs 31318,31316    # exact jobs instead of picking

Run from the checkout whose data/ is the live one (the main repo root), with PYTHONPATH at the code under test.
Every run is --review (never the final submit click) and --park (never waits on the human). Jobs run ONE AT A TIME.
Tabs: tabs open before the check are never touched (the human's sessions); of the tabs a job opened, only its final
page is kept; the report opens last. Needs the agent Chrome on CDP (default http://localhost:9222).
Grading: each (question, answer) of the run is graded by Claude (haiku) for relevance; every field left unfilled is
classed captcha / needs_you (knowledge only the candidate has) / gap (the agent should have filled it).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CDP = os.getenv("CAREER_AGENT_CDP_URL", "http://localhost:9222")
# channel -> substrings of the job's apply/job URL that identify it (first matching job per channel is taken)
CHANNELS = {
    "indeed": ["indeed.com"],                      # board -> Indeed Apply or the company's ATS
    "himalayas": ["himalayas.app"],
    "instahyre": ["instahyre.com"],
    "workatastartup": ["workatastartup.com"],
    "wellfound": ["wellfound.com"],
    "career_site": ["greenhouse.io", "lever.co", "myworkdayjobs.com", "avature.net", "oraclecloud.com", "keka.com",
                    "darwinbox.in", "smartrecruiters.com", "/career", "/jobs/", "/job/"],   # a company's own site
    "remoteok": ["remoteok.com"],
}
DEFAULT = ["indeed", "himalayas", "instahyre", "workatastartup", "wellfound", "career_site"]
NEVER = ("naukri.com", "iimjobs.com", "linkedin.com")      # one-click boards: the Apply click IS the submit


def tabs() -> dict:
    try:
        return {t["id"]: t["url"] for t in json.load(urllib.request.urlopen(CDP + "/json/list", timeout=10))
                if t.get("type") == "page"}
    except Exception:
        return {}


def close_tab(tid: str) -> None:
    try:
        urllib.request.urlopen(f"{CDP}/json/close/{tid}", timeout=5).read()
    except Exception:
        pass


def pick_jobs(conn, channels, per, spare=3, since="") -> list[tuple[str, list[tuple[int, str]]]]:
    """Per channel, `per` jobs plus spares: a posting found closed / already applied is replaced by the next one."""
    rows = conn.execute(
        "SELECT j.id, coalesce(nullif(j.apply_url,''), j.job_url) FROM jobs j JOIN match_scores m ON m.job_id=j.id "
        "WHERE coalesce(j.status,'new') IN ('new','') AND coalesce(j.expired,0)=0 "
        "AND j.id NOT IN (SELECT job_id FROM apply_queue WHERE job_id IS NOT NULL) "
        "AND j.id NOT IN (SELECT DISTINCT job_id FROM application_qa WHERE job_id IS NOT NULL) "
        "AND m.verdict IN ('Strong Fit','Good Fit','Moderate Fit') AND coalesce(j.fetched_at,'') >= ? "
        "ORDER BY (m.verdict='Strong Fit') DESC, (m.verdict='Good Fit') DESC, j.fetched_at DESC", (since,)).fetchall()
    out, used = [], set()
    for ch in channels:
        cands = []
        for jid, url in rows:
            u = (url or "").lower()
            if jid in used or any(b in u for b in NEVER) or not any(p in u for p in CHANNELS[ch]):
                continue
            if ch == "career_site" and any(p in u for c, ps in CHANNELS.items() if c != "career_site" for p in ps):
                continue                              # a board's own /jobs/ page is that board, not a company site
            cands.append((jid, url)); used.add(jid)
            if len(cands) >= per + spare:
                break
        out.append((ch, cands))
    return out


def outcome_class(reason: str) -> str:
    """ok = form reached and filled to the end; gone = nothing to apply to; else captcha / gap (the agent stopped)."""
    r = reason or ""
    if r.startswith("reached_submit") or r in ("parked", "pending_human"):
        return "ok"
    if r == "needs_answers":
        return "needs_you"
    if r.startswith("closed") or "already_applied" in r:
        return "gone"
    return "captcha" if "captcha" in r else "gap"


def run_job(jid: int, url: str, code_path: str, log_dir: Path) -> dict:
    res = Path(f"/tmp/live_check_{jid}.json")
    res.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": code_path, "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false"}
    with open(log_dir / f"{jid}.log", "w") as log:
        subprocess.run([sys.executable, "-m", "career_agent.apply", "--cdp-url", CDP, "--job-id", str(jid),
                        "--url", url, "--review", "--park", "--claude-assist", "--longform",
                        "--ask-wait-minutes", "2", "--result-json", str(res)],
                       stdout=log, stderr=subprocess.STDOUT, env=env, timeout=40 * 60)
    try:
        return json.loads(res.read_text())
    except Exception:
        return {"stopped_reason": "crashed"}


def answers(conn, jid: int, since: str) -> list[dict]:
    cols = ["kind", "label", "answer", "source", "status", "options_json"]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM application_qa WHERE job_id=? AND created_at>=? ORDER BY id",
                        (jid, since)).fetchall()
    last = {}                                        # one row per question: the last decision wins
    for r in rows:
        d = dict(zip(cols, r))
        last.pop(d["label"], None)
        last[d["label"]] = d
    return list(last.values())


GRADE_PROMPT = """You grade a job-application agent. Job: {title} at {company}.
For each item: the form's question, the field kind and options, and the agent's answer ("" = left blank).
Return ONLY a JSON list, one object per item in order: {{"i": n, "relevance": 0|1|2, "blank_class": "-"|"captcha"|"needs_you"|"gap", "note": "<=12 words"}}
relevance (only when answered): 2 = answers exactly what was asked, 1 = plausible but generic/partial, 0 = wrong or irrelevant.
blank_class (only when blank): captcha = a bot check; needs_you = only the candidate knows it (opinions, preferences, legal, references, salary not on file);
gap = the agent should have filled it from a résumé/profile (name, contact, education, experience, standard yes/no, a consent box).
Items:
{items}"""


def grade(job: dict, qa: list[dict]) -> list[dict]:
    if not qa:
        return []
    items = "\n".join(f"{i}. [{q['kind']}] {q['label'][:120]!r} options={str(q['options_json'] or '')[:120]} "
                      f"answer={str(q['answer'] or '')[:200]!r}" for i, q in enumerate(qa))
    prompt = GRADE_PROMPT.format(title=job.get("title", ""), company=job.get("company", ""), items=items)
    try:
        r = subprocess.run(["claude", "-p", "--model", "haiku", "--max-turns", "1", "--tools", ""],
                           input=prompt, capture_output=True, text=True, timeout=240)
        txt = r.stdout[r.stdout.find("["): r.stdout.rfind("]") + 1]
        return json.loads(txt)
    except Exception as e:
        return [{"i": i, "relevance": None, "blank_class": "?", "note": f"grader failed: {type(e).__name__}"}
                for i in range(len(qa))]


def report(results: list[dict], out: Path) -> None:
    def esc(x):
        return html.escape(str(x or ""))
    blocks, tot = [], {"answered": 0, "rel2": 0, "rel0": 0, "gap": 0, "needs_you": 0, "captcha": 0}
    stops = {"ok": 0, "needs_you": 0, "gone": 0, "captcha": 0, "gap": 0}
    for r in results:
        oc = outcome_class(r["result"].get("stopped_reason"))
        stops[oc] += 1
        rows = []
        for q, g in zip(r["qa"], r["grades"] + [{}] * (len(r["qa"]) - len(r["grades"]))):
            ans = str(q["answer"] or "")
            if ans:
                tot["answered"] += 1
                tot["rel2"] += g.get("relevance") == 2
                tot["rel0"] += g.get("relevance") == 0
                verdict = {2: "✅ relevant", 1: "🟡 partial", 0: "❌ wrong"}.get(g.get("relevance"), "?")
            else:
                c = g.get("blank_class", "?")
                tot[c] = tot.get(c, 0) + 1
                verdict = {"needs_you": "🙋 needs you", "captcha": "🤖 captcha", "gap": "⚠️ agent gap"}.get(c, "blank")
            rows.append(f"<tr><td>{esc(q['label'][:90])}</td><td>{esc(ans[:140])}</td><td>{esc(q['source'])}</td>"
                        f"<td>{verdict}</td><td>{esc(g.get('note'))}</td></tr>")
        blocks.append(f"<h2>{esc(r['channel'])} · {esc(r['job'].get('company'))} — {esc(r['job'].get('title'))}</h2>"
                      f"<p>outcome: <b>{esc(r['result'].get('stopped_reason'))}</b> "
                      f"{ {'ok': '✅', 'needs_you': '🙋 waiting on your answer', 'gone': '⏹ posting gone', 'captcha': '🤖 captcha', 'gap': '⚠️ agent stopped'}[oc]} · filled {esc(r['result'].get('filled'))}"
                      f" · <a href='{esc(r['result'].get('url') or r['url'])}'>final page</a></p>"
                      f"<table><tr><th>Question</th><th>Answer</th><th>Source</th><th>Verdict</th><th>Why</th></tr>"
                      + "".join(rows) + "</table>")
    pct = f"{100 * tot['rel2'] // tot['answered']}%" if tot["answered"] else "–"
    head = (f"<h1>Live check — {datetime.now().strftime('%Y-%m-%d %H:%M')}</h1><p>{len(results)} jobs · {tot['answered']} "
            f"answers, {pct} fully relevant, {tot['rel0']} wrong · blanks: {tot['gap']} agent gaps, {tot['needs_you']} "
            f"need you, {tot['captcha']} captcha</p><p>runs: {stops['ok']} reached the end, {stops['gap']} agent stopped, "
            f"{stops['captcha']} captcha, {stops['gone']} posting gone</p>")
    css = ("body{font:14px -apple-system,sans-serif;margin:24px;max-width:1200px}table{border-collapse:collapse;width:100%}"
           "td,th{border:1px solid #ddd;padding:4px 6px;vertical-align:top;text-align:left}th{background:#f4f4f4}"
           "h2{margin-top:28px}")
    out.write_text(f"<!doctype html><meta charset=utf-8><title>Live check</title><style>{css}</style>{head}"
                   + "".join(blocks))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channels", default=",".join(DEFAULT))
    ap.add_argument("--per", type=int, default=1)
    ap.add_argument("--jobs", default="", help="comma-separated job ids (skips picking)")
    ap.add_argument("--since", default="", help="only jobs fetched at/after this time (e.g. today's refresh)")
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--code", default=os.getenv("PYTHONPATH", "src"), help="PYTHONPATH of the agent code under test")
    a = ap.parse_args()
    conn = sqlite3.connect(a.db)
    if a.jobs:
        picks = []
        for j in a.jobs.split(","):
            u = conn.execute("SELECT coalesce(nullif(apply_url,''),job_url) FROM jobs WHERE id=?", (int(j),)).fetchone()
            picks.append(("given", [(int(j), u[0] if u else "")]))
        a.per = len(picks)
    else:
        picks = pick_jobs(conn, [c for c in a.channels.split(",") if c in CHANNELS], a.per, since=a.since)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    log_dir = Path("data/agent_runs/live_check") / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    human_tabs = set(tabs())                          # never touched
    results = []
    for ch, jid, url in ((ch, jid, url) for ch, cands in picks for jid, url in cands):
        if sum(r["channel"] == ch and outcome_class(r["result"].get("stopped_reason")) != "gone" for r in results) >= a.per:
            continue                                  # this channel already has its live run(s)
        job = dict(zip(["title", "company"], conn.execute("SELECT title, company FROM jobs WHERE id=?", (jid,)).fetchone()))
        print(f"=== {ch} {jid} {job['company']} — {job['title']}", flush=True)
        since = datetime.now(timezone.utc).isoformat()
        before = set(tabs())
        res = run_job(jid, url, a.code, log_dir)
        final = (res.get("url") or "").split("#")[0]
        new = {t: u for t, u in tabs().items() if t not in before and t not in human_tabs}
        keep = next((t for t, u in new.items() if final and u.split("#")[0] == final), None) or next(iter(new), None)
        for tid in new:                               # only this job's final page survives (else its newest tab)
            if tid != keep:
                close_tab(tid)
        qa = answers(sqlite3.connect(a.db), jid, since)
        g = grade(job, qa)
        results.append({"channel": ch, "job": job, "url": url, "result": res, "qa": qa, "grades": g})
        print(f"--- {jid} {res.get('stopped_reason')} filled={res.get('filled')} questions={len(qa)}", flush=True)
    out = Path("data/reports") / f"live_check_{stamp}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    report(results, out)
    (log_dir / "results.json").write_text(json.dumps(results, default=str, indent=1))
    try:                                              # the report opens last, beside the final pages
        urllib.request.urlopen(urllib.request.Request(f"{CDP}/json/new?{out.resolve().as_uri()}", method="PUT"),
                               timeout=10).read()
    except Exception:
        pass
    print(f"REPORT {out.resolve()}", flush=True)


if __name__ == "__main__":
    main()
