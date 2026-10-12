"""How efficient and apt were the agent's answers? Compares two sets of filled applications (application_qa):
AFTER = the latest run of each given job, BEFORE = every job run before a cut-off date. Only answers are judged here —
not navigation (a page the agent never reached has no answers to judge).

  PYTHONPATH=src python3 scripts/answer_quality_report.py --data <checkout>/data --after-jobs 1,2,3 --before 2026-10-11

Per field: answered or left for you, and WHICH tier answered (question bank / facts plan / rules / long-form / you).
Short answers: checked exactly against the stored facts where the right value is known (name, email, phone, CTC,
notice, years, location, links, education...), else graded by the LOCAL model with the fact sheet (values stay on the
machine). A non-question that got a value (search box, junk label) counts as a wrong fill. Long answers: answer
relevancy + faithfulness against the candidate's project material, judged by Claude Haiku (as in longform_iterate)."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_JUNK = re.compile(r"^(cards\[|rec-form|\*$|captcha|search|enter keyword|select experience|find\b)", re.I)
_DIGITS = lambda s: re.sub(r"\D", "", str(s or ""))


def tier(row) -> str:
    src, basis = row["source"] or "", row["basis"] or ""
    if not (row["answer"] or "").strip() and src not in ("attestation",):
        return "left for you"
    if "plan from your facts" in basis:
        return "facts plan (new)"
    if src == "qbank":
        return "question bank"
    if src == "qbank_likely":
        return "question bank (likely)" if "composed" not in basis else "bank: composed from facts"
    if src in ("resume", "standard", "attestation", "flag"):
        return "rules"
    if src == "judgment":
        return "long-form / judgment"
    if src == "human":
        return "you"
    return src or "other"


def expected(label: str, contact: dict, bank: dict):
    """The stored right value for a field whose meaning is unambiguous from its label, else None (graded by model)."""
    l = (label or "").lower()
    pick = [
        (r"e-?mail", [contact.get("email")]),
        (r"first name", [str(contact.get("full_name", "")).split()[0] if contact.get("full_name") else None]),
        (r"last name|surname", [str(contact.get("full_name", "")).split()[-1] if contact.get("full_name") else None]),
        (r"full name|^name\b|your name", [contact.get("full_name")]),
        (r"linkedin", [contact.get("linkedin_url")]),
        (r"github", [contact.get("github_url")]),
        (r"notice|available to join|joining time", ["30"]),
        (r"current (salary|ctc)|present (salary|ctc)", ["25", "2500000", "25 lpa"]),
        (r"expected (salary|ctc)|desired salary", ["35", "3500000", "35 lpa"]),
        (r"years of (total )?(work )?experience$|^experience( \(years\))?$|total experience", ["3"]),
        (r"current location|current city|^location$", ["mumbai"]),
        (r"graduation year|year of graduation|passing year", ["2023"]),
        (r"university|college|institute", ["indian institute of technology", "iit"]),
        (r"gender", ["male"]),
        (r"current (company|employer)|company name", ["tata aig"]),
        (r"current (job )?title|current role|designation", ["data scientist"]),
    ]
    for pat, vals in pick:
        if re.search(pat, l):
            return [str(v).lower() for v in vals if v]
    if re.search(r"phone|mobile|whats ?app|contact (no|number)", l):
        return ["phone:" + _DIGITS(contact.get("phone"))[-10:]]
    return None


def exact_ok(answer: str, exp: list) -> bool:
    a = str(answer or "").lower()
    for e in exp:
        if e.startswith("phone:"):
            if _DIGITS(a)[-10:] == e[6:] or (len(_DIGITS(a)) <= 3 and "+" in a):      # the number, or a country-code box
                return True
        elif e in a or _DIGITS(a) and _DIGITS(a) == _DIGITS(e) and _DIGITS(e):
            return True
    return False


def local_judge():
    import urllib.request

    def llm(prompt: str) -> str:
        body = json.dumps({"model": "gemma4:26b", "prompt": prompt, "stream": False, "think": False,
                           "options": {"temperature": 0}}).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", body, {"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=600).read())["response"]
    return llm


def grade_short(label, kind, answer, sheet: str, llm) -> str:
    raw = _THINK.sub("", llm(
        "A job-application form field was filled for a candidate. Using ONLY the candidate's stored facts, is the value "
        "correct for what the field asks? A value in a different but valid format still counts as correct.\n"
        f"FACTS:\n{sheet}\n\nFIELD ({kind}): {label}\nVALUE: {answer}\n\n"
        'Reply with ONLY JSON: {"verdict": "correct" | "wrong" | "unverifiable", "why": "<short>"}') or "")
    i = raw.find("{")
    try:
        return json.JSONDecoder().raw_decode(raw[i:])[0].get("verdict", "unverifiable") if i >= 0 else "unverifiable"
    except ValueError:
        return "unverifiable"


def latest_rows(conn, job_ids):
    rows = []
    for jid in job_ids:
        rk = conn.execute("SELECT run_key FROM application_qa WHERE job_id=? ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
        if rk:
            rows += conn.execute("SELECT * FROM application_qa WHERE job_id=? AND run_key=? ORDER BY id", (jid, rk[0])).fetchall()
    return rows


def evaluate(rows, sheet, contact, bank, llm, judge, kb_text, long_limit=30):
    from career_agent.longform import metrics as M
    from career_agent.longform.kb import Chunk
    out = {"fields": 0, "junk_filled": 0, "tiers": {}, "short": {"exact_ok": 0, "exact_wrong": 0, "model_correct": 0,
           "model_wrong": 0, "unverifiable": 0}, "long": [], "wrong_examples": []}
    passages = [Chunk(f"p{i}", "passage", t) for i, t in enumerate(kb_text)]
    longs = 0
    for r in rows:
        label, ans, kind = (r["label"] or "").strip(), (r["answer"] or "").strip(), r["kind"]
        if kind in ("file", "button") or r["source"] == "attestation":
            continue
        if _JUNK.match(label) or not label:
            out["junk_filled"] += bool(ans)
            continue
        out["fields"] += 1
        t = tier(r)
        out["tiers"][t] = out["tiers"].get(t, 0) + 1
        if not ans or t == "you":
            continue
        if kind == "textarea" and len(ans.split()) > 25:
            if longs < long_limit:
                longs += 1
                items = M.explicit_asks(label, judge)
                sc = M.score_answer(label, ans, passages, judge, items=items)
                out["long"].append({"q": label[:90], "ar": sc.get("answer_relevancy"), "f": sc.get("faithfulness"), "tier": t})
            continue
        exp = expected(label, contact, bank)
        if exp is not None:
            ok = exact_ok(ans, exp)
            out["short"]["exact_ok" if ok else "exact_wrong"] += 1
            if not ok:
                out["wrong_examples"].append((label[:60], ans[:60], t, "expected " + exp[0][:30]))
        else:
            v = grade_short(label, kind, ans, sheet, llm)
            key = {"correct": "model_correct", "wrong": "model_wrong"}.get(v, "unverifiable")
            out["short"][key] += 1
            if v == "wrong":
                out["wrong_examples"].append((label[:60], ans[:60], t, "model: wrong"))
    return out


def summarize(name, res) -> list[str]:
    s, n = res["short"], res["fields"]
    answered = n - res["tiers"].get("left for you", 0) - res["tiers"].get("you", 0)
    judged = s["exact_ok"] + s["exact_wrong"] + s["model_correct"] + s["model_wrong"]
    right = s["exact_ok"] + s["model_correct"]
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    lines = [f"### {name}", "", f"- Real questions: **{n}**; answered without you: **{answered}** "
             f"({round(100 * answered / n) if n else 0}%); left for you: {res['tiers'].get('left for you', 0)}",
             f"- Short answers judged: {judged}; **correct {right} ({round(100 * right / judged) if judged else 0}%)**, "
             f"wrong {judged - right}; could not verify: {s['unverifiable']}",
             f"  - exact check vs stored facts: {s['exact_ok']} right / {s['exact_wrong']} wrong; "
             f"model-graded: {s['model_correct']} right / {s['model_wrong']} wrong",
             f"- Non-questions that got a value (search boxes, junk labels): {res['junk_filled']}",
             f"- Long answers judged: {len(res['long'])}; answer relevancy **{mean([x['ar'] for x in res['long'] if x['ar'] is not None])}**, "
             f"faithfulness **{mean([x['f'] for x in res['long'] if x['f'] is not None])}**", "",
             "| Who answered | Fields | Share |", "|---|---|---|"]
    for t, k in sorted(res["tiers"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {t} | {k} | {round(100 * k / n) if n else 0}% |")
    return lines + [""]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--after-jobs", required=True, help="comma-separated job ids (latest run of each)")
    ap.add_argument("--before", default="2026-10-11", help="BEFORE = runs created before this date")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    from career_agent.memory import facts as F
    from career_agent.memory.facts import claude_cli_llm
    from job_dashboard.apply.store import get_application_profile

    data = Path(a.data)
    conn = sqlite3.connect(f"file:{data / 'jobs.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    contact = get_application_profile(conn) or {}
    skills = json.loads((data / "answer_style" / "ingredients.json").read_text())["skills_pool"]
    fs = F.build(conn, contact, skills)
    sheet = "\n".join(f"- {k}: {F.render(v['value'])}" for k, v in fs.items() if v["value"] not in (None, ""))
    bank = {k: v["value"] for k, v in fs.items()}
    units = json.loads((data / "answer_style" / "ingredients.json").read_text())["units"]
    kb_text = [f"{u.get('title')} ({u.get('org')}): {u.get('source', '')[:1400]}" for u in units]
    llm = local_judge()
    judge = claude_cli_llm("haiku", timeout=180, system="You are a strict, literal evaluator of job-application answers. Reply with JSON only.")

    after_ids = [int(x) for x in a.after_jobs.split(",") if x.strip()]
    before_ids = [r[0] for r in conn.execute("SELECT DISTINCT job_id FROM application_qa WHERE created_at < ? AND job_id IS NOT NULL",
                                             (a.before,))]
    before = evaluate(latest_rows(conn, before_ids), sheet, contact, bank, llm, judge, kb_text)
    after = evaluate(latest_rows(conn, after_ids), sheet, contact, bank, llm, judge, kb_text)
    lines = [f"# Answer quality: before vs after the database + router changes ({date.today()})", "",
             f"BEFORE: {len(before_ids)} jobs the agent filled before {a.before} (old pipeline). "
             f"AFTER: {len(after_ids)} live dashboard jobs filled on the integrated branch, review mode (nothing submitted).", ""]
    lines += summarize("Before", before) + summarize("After", after)
    lines += ["## Wrong short answers after the changes", "", "| Field | Value | Answered by | Check |", "|---|---|---|---|"]
    lines += [f"| {l} | {v} | {t} | {w} |" for l, v, t, w in after["wrong_examples"]] or ["| (none) | | | |"]
    out = Path(a.out or data / "reports" / f"answer_quality_{date.today()}.md")
    out.write_text("\n".join(lines) + "\n")
    (out.with_suffix(".json")).write_text(json.dumps({"before": before, "after": after}, indent=1, default=str))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
