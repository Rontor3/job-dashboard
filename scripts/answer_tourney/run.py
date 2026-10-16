"""Answer-method tournament on a held-out case set (cases.json). Reuses the bench's field/outcome/env setup.

  PYTHONPATH=src python3 <tourney>/run.py [--methods current,guarded,compiled_haiku,<contestant>] [--cases N|id,id]
      [--out data/answer_tourney/results.csv] [--dry] [--learn]
  --dry: resolve gold only, print which cases fail to resolve.
  --learn: every ask with a known answer is saved to the bank (as the user would on the dashboard); the goal metric
           is then asks (fewest questions to the user) at zero wrong, and `reused` counts answers from taught entries.

Contestants: contestants/<name>.py with answer(env, i, case) -> str|None and optional setup(env).
case is the bench tuple (group, kind, label, options, job, gold, lenient); env as the bench builds it, plus
env['haiku'] (Counted Claude Haiku via CLI — send it schema/question only, never fact values), env['facts'].
Each method gets a fresh temp copy of jobs.db and a fresh plan cache. The real DB is never written."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "src"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bench = _load("answer_methods_bench", REPO / "scripts" / "answer_methods_bench.py")
BASELINES = {"current": bench.m_current, "guarded": bench.m_guarded, "compiled_haiku": bench.m_compiled_haiku,
             "current_nollm": bench.m_current_nollm, "compiled": bench.m_compiled}


def contestants() -> dict:
    out = {}
    for p in sorted((HERE / "contestants").glob("*.py")):
        mod = _load(f"contestant_{p.stem}", p)
        if hasattr(mod, "answer"):
            out[p.stem] = mod
    return out


def make_env(db_src: Path, data: Path):
    from career_agent.memory import facts as F
    from career_agent.memory import qbank
    from career_agent.memory.candidate_profile import load_candidate_profile
    from job_dashboard.apply.store import get_application_profile
    from job_dashboard.letter.draft import make_default_llm
    tmp = Path(tempfile.mkdtemp()) / "jobs.db"
    shutil.copy(db_src, tmp)                                   # never touch the real DB
    conn = sqlite3.connect(tmp)
    contact = get_application_profile(conn) or {}
    skills = json.loads((data / "answer_style" / "ingredients.json").read_text())["skills_pool"]
    env = {"conn": conn, "contact": contact, "embed": qbank.default_embed,
           "profile": load_candidate_profile(conn, contact=contact), "llm": bench.Counted(make_default_llm()),
           "notes": {}, "plans": {}, "skills": skills,
           "haiku": bench.Counted(F.claude_cli_llm("haiku"))}  # lazy: no call until used
    env["facts"] = F.build(conn, contact, skills)
    return env


# ── gold ─────────────────────────────────────────────────────────────────────
def _gold_ns(env, job, opts):
    from career_agent.memory import facts as F
    f = {k: v["value"] for k, v in env["facts"].items()}

    def inr(m):
        return m["amount"] * F._TO_INR[m["currency"]] * F._PERIOD[m["period"]]

    def num(x):
        return F.render(float(x))

    def has(hay, needle):
        items = hay if isinstance(hay, list) else [hay] if hay else []
        return any(str(needle).lower() in str(x).lower() for x in items)

    def yn(b):
        if b is None:
            raise ValueError("bool fact is None")
        return "yes" if b else "no"

    def age(d):
        t = date.today()
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))

    def band(y, options):
        hits = []
        for o in options:
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", o)]
            lo, hi = (nums[0], nums[1]) if len(nums) > 1 else (nums[0], 1e9) if nums else (None, None)
            if lo is not None and lo <= y <= hi:
                hits.append(o)                                 # a boundary value accepts both bands
        return hits

    def within(days, options):
        def d(o):
            if re.search(r"immediate", o, re.I):
                return 0
            m = re.search(r"(\d+)\s*(day|week|month)", o, re.I)
            return int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2).lower()] if m else None
        ok = sorted((d(o), o) for o in options if d(o) is not None and d(o) >= days)
        return [ok[0][1]] if ok else [o for o in options if re.search(r"other", o, re.I)]

    return {"f": f, "job": job, "opts": opts, "inr": inr, "num": num, "has": has, "yn": yn, "age": age,
            "band": band, "within": within, "LEVELS": F.LEVELS,
            "lakh": lambda m: num(round(inr(m) / 1e5, 2)),
            "moneyforms": lambda m: [m["text"], num(round(inr(m) / 1e5, 2)), num(round(inr(m)))],
            "usd_month": lambda m: [num(round(inr(m) / 88 / 12)), num(round(inr(m) / 88 / 12, 2))],
            "skill": lambda s: (f.get("skills") or {}).get(s.lower()) or 0}


def resolve(env, case):
    """Gold refs -> acceptable values (None = must escalate). Raises when a ref can't resolve."""
    from career_agent.memory import facts as F
    gold = case["gold"]
    if gold is None:
        return None
    out = []
    for g in gold:
        if g.startswith("@expr:"):
            v = eval(g[6:], _gold_ns(env, case["job"], case["options"]))   # our own case file, not input
            out.extend(v if isinstance(v, list) else [v])
        elif g.startswith("@fact."):
            key, _, fld = g[6:].partition(".")
            v = env["facts"][key]["value"]
            out.append(F.render(v[fld] if fld else v))
        elif g.startswith("@"):
            out.extend(bench.resolve_gold(env["conn"], env["contact"], [g]))
        else:
            out.append(g)
    out = [str(x) for x in out if x not in (None, "")]
    if not out:
        raise ValueError("gold resolved to nothing")
    return out


def outcome(value, gold, lenient):
    if value in (None, "") or gold is None:
        return bench.outcome(value, gold, lenient)
    ok = any(re.search(g[3:], str(value)) if g.startswith("re:") else bench.same(value, g) for g in gold)
    return "correct" if ok else "wrong"


def redact(value, contact):
    for k in ("phone", "email"):
        pv = str(contact.get(k) or "")
        if pv and value and (str(value).strip().lower() == pv.lower()
                             or (k == "phone" and bench.same(value, pv))):
            return f"<profile:{k}>"
    return value


def ollama_up() -> bool:
    import os
    import urllib.request
    try:
        urllib.request.urlopen(os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/version", timeout=5)
        return True
    except OSError:
        return False


def learn(env, case, answer) -> str:
    """The user answers an asked question once: it becomes a bank entry and every method's knowledge is rebuilt."""
    from career_agent.memory import facts as F
    from career_agent.memory import qbank
    eid = qbank.add_entry(env["conn"], question=case["label"], kind=case["kind"], answer=answer, embed=env["embed"])
    env["facts"] = F.build(env["conn"], env["contact"], env["skills"])
    env.pop("fc", None)                                        # retrieval index over the old facts
    env["plans"].clear()                                       # cached MISSING plans predate the new fact
    return eid


# ── run ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="current,guarded,compiled_haiku")
    ap.add_argument("--cases", default=None, help="N (first N) or comma-separated case ids")
    ap.add_argument("--out", default=str(REPO / "data" / "answer_tourney" / "results.csv"))
    ap.add_argument("--data", default=str(REPO / "data"))
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--learn", action="store_true",
                    help="on an ask with a known gold answer, simulate the user answering: save it to the bank "
                         "(qbank.add_entry, as the dashboard does) so later related questions can reuse it")
    args = ap.parse_args()
    data = Path(args.data)
    cases = json.loads((HERE / "cases.json").read_text())
    if args.cases:
        cases = cases[:int(args.cases)] if args.cases.isdigit() else [c for c in cases if c["id"] in args.cases.split(",")]
    pool = {**BASELINES, **contestants()}

    if args.dry:
        env = make_env(data / "jobs.db", data)
        bad = 0
        for c in cases:
            try:
                g = resolve(env, c)
                print(c["id"], "escalate" if g is None else f"{len(g)} gold value(s)")
            except Exception as e:
                bad += 1
                print(c["id"], "GOLD ERROR", type(e).__name__, e)
        print(f"{len(cases)} cases, {bad} gold errors")
        return

    rows, summary = [], {}
    for name in args.methods.split(","):
        m = pool[name]
        fn = m if callable(m) else m.answer
        env = make_env(data / "jobs.db", data)                 # fresh DB copy + plan cache per method
        if not callable(m) and hasattr(m, "setup"):
            m.setup(env)
        stats = {"correct": 0, "wrong": 0, "missed": 0, "ok_escalate": 0, "gold_error": 0, "learned": 0, "reused": 0}
        learned = set()
        t0 = time.monotonic()
        for i, c in enumerate(cases):
            tup = (c["group"], c["kind"], c["label"], c["options"], c["job"], c["gold"], c["lenient"])
            t1 = time.monotonic()
            try:
                value = fn(env, i, tup)
            except Exception as e:                             # a crash is a miss, and says so
                env["notes"][i] = f"CRASH {type(e).__name__}: {e}"[:300]
                value = None
            secs = round(time.monotonic() - t1, 2)
            value = None if value in (None, "") else str(value)
            if value is None and not ollama_up():               # a dead local model is not a method's miss
                sys.exit(f"Ollama unreachable at {name}/{c['id']}: results so far are not saved; restart and rerun")
            gold = None
            try:
                gold = resolve(env, c)
                res = outcome(value, gold, c["lenient"])
            except Exception as e:
                res, env["notes"][i] = "gold_error", f"gold: {e}"
            stats[res] += 1
            note = str(env["notes"].get(i, ""))
            if res == "correct" and any(e in note for e in learned):
                stats["reused"] += 1                           # answered from something the user taught earlier
            if args.learn and value is None and gold:
                ans = next((g for g in gold if not g.startswith("re:")), None)
                if ans:
                    learned.add(learn(env, c, ans))
                    stats["learned"] += 1
                    env["notes"][i] = f"{note} | learned"
            shown = redact(value, env["contact"])
            rows.append({"method": name, "case_id": c["id"], "group": c["group"], "question": c["label"][:120],
                         "answer": "" if shown is None else shown, "outcome": res,
                         "note": str(env["notes"].pop(i, ""))[:300], "seconds": secs})
            print(f"{name:14} {c['id']:6} {res:12} {secs:6.1f}s {c['label'][:60]!r} -> {shown!r}", flush=True)
        stats["asks"] = stats["missed"] + stats["ok_escalate"]   # questions the user had to answer
        stats.update(llm_calls=env["llm"].calls, haiku_calls=env["haiku"].calls,
                     seconds=round(time.monotonic() - t0, 1), n=len(cases))
        summary[name] = stats
        print(f"== {name}: {json.dumps(stats)}", flush=True)
        env["conn"].close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
