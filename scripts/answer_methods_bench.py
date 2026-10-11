"""Compare ways of answering short form questions from what is already stored.

Cases are the questions the agent left unanswered on real applications (application_qa, status needs_answer,
no source), each with the answer the stored data implies. Long-form textareas are out of scope (longform/).
Gold values that are personal data are references (@profile.<col>, @bank.<entry>) resolved at run time, so
nothing personal is written in this file. Runs on a throwaway copy of jobs.db; the real DB is never written.

  PYTHONPATH=src python3 scripts/answer_methods_bench.py [--methods current,factsheet] [--out data/reports/x.csv]

Outcomes: correct | wrong (a value that is not the gold one — the harmful case) | missed (no value, gold had
one) | ok_escalate (no value, and escalating is fine: gold is None or the case is lenient)."""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YN = ["Yes", "No"]
KH = {"company": "Kraft Heinz", "location": "KA, IN"}
JC = {"company": "JumpCloud", "location": "India"}
SC = {"company": "Scalio", "location": "Bengaluru, Karnataka, India (On-site)"}
CR = {"company": "CRUCIFER AI TECHNOLOGIES", "location": "Bengaluru, Karnataka, India (On-site)"}
VB = {"company": "Vbeyond Corporation", "location": "Gurugram"}
VI = {"company": "Variety Innovation Venture", "location": "Gurugram"}

# (group, kind, label, options, job, gold values or None = must escalate, lenient = escalating is acceptable)
CASES = [
    ("in-store", "combobox", "Are you 18 years of age or older?", YN, KH, ["yes"], False),
    ("in-store", "combobox", "Are you currently under a non-compete agreement with a prior employer that would effect your ability to work at Kraft Heinz?", YN, KH, ["no"], False),
    ("in-store", "combobox", "Are any of your direct family members (spouse, mother, father, brother, sister, son or daughter) current Kraft Heinz employees?", YN, KH, ["no"], False),
    ("in-store", "text", "What is your current CTC?", [], {}, ["@profile.current_ctc"], False),
    ("in-store", "tel", "WhatsApp Number", [], JC, ["@profile.phone"], False),
    ("in-store", "select", "Source*", [], {"company": "Thales"}, ["@bank.referral_source"], False),
    ("in-store", "checkbox", "I want to be considered for other Job Opportunities. *", [], {"company": "Thales"}, ["yes"], False),
    ("in-store", "radio_group", "Are you available for a interview?(Virtual)", YN, {"company": "Infosys"}, ["yes"], False),
    ("in-store", "select", "Pursuing/ Completed *", [], {}, ["completed"], True),
    ("in-store", "select", "Examination Passed *", [], {}, ["@bank.highest_degree"], True),
    ("in-store", "select", "Country Phone Code*", [], {"company": "Thales"}, ["+91", "91", "india (+91)"], False),
    ("derived", "radio_group", "Do you currently live in India?", YN, JC, ["yes"], False),
    ("derived", "radio_group", "Are you fluent and able to conduct business in the English Language (both spoken and written)?", YN, JC, ["yes"], False),
    ("derived", "select", "What is your level of proficiency in English?*", [], CR, ["fluent"], False),
    ("derived", "radio_group", "Are you willing to work full-time, on-site in Bengaluru?", YN, SC, ["yes"], False),
    ("derived", "radio_group", "Is your Current Salary Above USD 3500?", YN, CR, ["no"], True),
    ("derived", "radio_group", "Are you okay with up to 6 LPA? If not, then do not apply.", YN, {}, ["no"], False),
    ("derived", "text", "Other Visa(If any)", [], {"company": "Birlasoft"}, ["none", "no", "na", "n/a", "@bank.current_visa_status"], True),
    ("derived", "select", "Please choose your notification language *", [], {"company": "Siemens"}, ["english"], True),
    ("derived", "radio_group", "Do you have consistent internet access?", YN, JC, ["yes"], True),
    ("derived", "radio_group", "Do you have consistent access to power/electricity?", YN, JC, ["yes"], True),
    ("derived", "radio_group", "Do you have consistent phone/mobile/cellular access", YN, JC, ["yes"], True),
    ("derived", "radio_group", "Do you have hands-on experience building reinforcement learning (RL) environments or agentic systems?", YN, {"company": "Appen"}, ["yes"], True),
    ("years", "text", "How many years of experience do you have in Python?", [], VB, ["3"], False),
    ("years", "text", "How many years of work experience do you have with Python (Programming Language)?", [], CR, ["3"], False),
    ("years", "text", "How many years of experience do you have in Linux?", [], VI, ["3"], False),
    ("years", "text", "How many years of work experience do you have with Azure OpenAI?", [], CR, ["3"], False),
    ("years", "text", "How many years of work experience do you have with AI for Data Scientists?", [], CR, ["2"], False),
    ("years", "text", "How many years of experience do you have in SQL?", [], VB, ["2", "3"], True),
    ("years", "text", "How many years of experience do you have in Generative Ai?", [], VB, ["2", "3"], True),
    ("years", "text", "How many years of experience do you have in ROS?", [], VI, ["0"], True),
    ("years", "text", "How many years of experience do you have in ROS 2?", [], VI, ["0"], True),
    ("years", "text", "How many years of experience do you have in Kinematics?", [], VI, ["0"], True),
    ("years", "text", "How many years of experience do you have in AI/ML (UAV)?", [], {}, ["0"], True),
    ("not-stored", "combobox", "Are you currently under an agreement with a prior employer covering patents or confidential/proprietary information that would effect your ability to work at Kraft Heinz?", YN, KH, None, True),
    ("not-stored", "tel", "Alternate Number", [], {"company": "Birlasoft"}, None, True),
    ("not-stored", "text", "Percentage *", [], {"company": "Naghavi Fintech"}, None, True),
    ("not-stored", "radio_group", "Visibility as candidate", [], {"company": "Siemens"}, None, True),
    ("not-stored", "select", "Submission of Identification Copies *", [], {}, None, True),
    ("junk", "select", "cards[46bf994f-a9a2-4257-a2ea-d0ffb6f00038][field0]", [], JC, None, True),
    ("junk", "text", "Captcha", [], {}, None, True),
    ("junk", "text", "*", [], {"company": "Siemens"}, None, True),
    ("junk", "text", "Enter keyword, designation, or companies", [], {}, None, True),
    ("junk", "text", "Select experience", [], {}, None, True),
]

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def norm(v) -> str:
    s = str(v).strip().lower()
    s = re.sub(r"\s*(lpa|lakhs?|years?|yrs?)\b\.?", "", s)
    return re.sub(r"\s+", " ", s).strip(" .")


def same(value, gold) -> bool:
    a, b = norm(value), norm(gold)
    if a == b:
        return True
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    if len(db) >= 10:                                  # phone: compare the last 10 digits
        return da[-10:] == db[-10:]
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def resolve_gold(conn, contact, gold):
    if gold is None:
        return None
    from career_agent.memory import qbank
    out = []
    for g in gold:
        if g.startswith("@profile."):
            out.append(str(contact.get(g.split(".", 1)[1]) or ""))
        elif g.startswith("@bank."):
            e = qbank.get_entry(conn, g.split(".", 1)[1])
            out.append(str((e or {}).get("answer") or ""))
        else:
            out.append(g)
    return [g for g in out if g]


def outcome(value, gold, lenient) -> str:
    if value in (None, ""):
        return "ok_escalate" if gold is None or lenient else "missed"
    if gold is None:
        return "wrong"
    return "correct" if any(same(value, g) for g in gold) else "wrong"


def field(i, kind, label, options):
    from career_agent.browser.form_model import Field, guess_purpose
    return Field(ref=f"f{i}", kind=kind, label=label, required=False, options=list(options),
                 purpose=guess_purpose(label, kind), input_type="tel" if kind == "tel" else "")


class Counted:
    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def __call__(self, prompt):
        self.calls += 1
        return self.fn(prompt)


# ── methods: (env, case_index, case) -> value or None ────────────────────────
def m_current(env, i, case, *, use_llm=True):
    """The live ladder minus the free-text judge: question bank, then the rule mapper."""
    from career_agent.memory.qbank_memory import QBankMemory
    from career_agent.orchestrator.answering import answer_fields
    _, kind, label, options, job, _, _ = case
    f = field(i, kind, label, options)
    learn = QBankMemory(env["conn"], embed=env["embed"], llm=env["llm"] if use_llm else None,
                        job=job, contact=env["contact"])
    decisions, _ = answer_fields([f], {"learn": learn, "profile": env["profile"]})
    for d in decisions:
        if d.action in ("check", "uncheck"):
            return "Yes" if d.action == "check" else "No"
        if d.value not in (None, "", True, False):
            return str(d.value)
    return None


def m_current_nollm(env, i, case):
    return m_current(env, i, case, use_llm=False)


def all_facts(env, job) -> list[tuple[str, str, str]]:
    """[(id, question, value)] — every stored fact: profile columns and every answered bank entry
    (rule entries resolved for this job; a rule's raw table is shown when it can't resolve alone)."""
    from career_agent.memory import qbank
    from career_agent.memory.qbank_match import resolve_value
    conn, contact = env["conn"], env["contact"]
    out = [(f"profile.{k}", k.replace("_", " "), str(v)) for k, v in contact.items()
           if v not in (None, "") and k != "updated_at"]
    for e in qbank.entries(conn):
        if e.get("topic") == "story":
            continue
        v = resolve_value(conn, e, question=e["question"], escape=None, job=job, contact=contact)
        if e.get("rule") == "years_in_skill":
            v = e.get("answer")                         # the whole table, not the default it resolves to
        if v not in (None, ""):
            out.append((e["id"], e["question"], str(v)))
    out.append(("today", "today's date", date.today().isoformat()))
    return out


def ask_facts(env, case, facts):
    """One model call: answer from these facts only, cite them, or NONE."""
    _, kind, label, options, job, _, _ = case
    lines = "\n".join(f"[{fid}] {q} -> {v}" for fid, q, v in facts)
    opt = f"\nThe answer must be exactly one of: {options}" if options else ""
    prompt = ("You fill a job application form for a candidate using ONLY the stored facts below.\n"
              f"Job: {job.get('company') or 'unknown company'}, {job.get('location') or 'unknown location'}\n"
              f"Form field ({kind}): {label}{opt}\n\nStored facts:\n{lines}\n\n"
              "Rules: answer only if the facts settle it, directly or by simple reasoning (comparison, arithmetic, "
              "a stored level implying a yes/no). A skill or experience not in the facts means none of it. If the "
              "field is not a real question, or the facts do not settle it, answer NONE.\n"
              'Reply with JSON only: {"value": "...", "facts": ["fact ids used"]}')
    try:
        reply = _THINK.sub("", env["llm"](prompt) or "")
        obj, _ = json.JSONDecoder().raw_decode(reply[reply.find("{"):])
    except Exception:
        return None
    value = str(obj.get("value") or "").strip()
    cited = [c for c in obj.get("facts") or [] if c in {fid for fid, _, _ in facts}]
    if not value or value.upper() == "NONE" or not cited:
        return None                                     # an uncited value is a guess: refuse it
    if options and value not in options:
        return None
    return value


def m_factsheet(env, i, case):
    """The model sees every stored fact (a few hundred lines) and answers with citations."""
    return ask_facts(env, case, all_facts(env, case[4]))


def m_topk(env, i, case, k=8):
    """Same, but only the k facts most similar to the question (retrieval-limited)."""
    import numpy as np
    facts = all_facts(env, case[4])
    vecs = env["embed"]([f"{q}: {v}" for _, q, v in facts])
    sims = vecs @ env["embed"]([case[2]])[0]
    top = [facts[j] for j in np.argsort(-sims)[:k]] + [f for f in facts if f[0] == "today"]
    return ask_facts(env, case, top)


def m_hybrid(env, i, case):
    """The live ladder first; the fact sheet only for what it leaves unanswered."""
    return m_current(env, i, case) or m_factsheet(env, i, case)


_YEARS = re.compile(r"\byears?\b.*\b(?:in|with|of)\s+(.+?)\s*\??\s*$", re.I)
_DIAL = re.compile(r"\b(country|dial\w*|calling)\b.*\bcode\b|\bcode\b.*\bcountry\b", re.I)
_ASKS = re.compile(r"^\s*(are|is|do|does|did|have|has|how|what|which|when|where|why|will|would|can|could|should)\b", re.I)


def skill_years(env, label):
    """'years of X': the stored table if X is in it, the default if X is a skill you list, else 0."""
    m = _YEARS.search(label)
    if not m:
        return None
    from career_agent.memory import qbank
    skill = re.sub(r"\(.*?\)", "", m.group(1)).strip().lower()
    table = dict(p.split("=", 1) for p in re.split(r"\s*,\s*", (qbank.get_entry(env["conn"], "skill_years") or {})
                                                          .get("answer") or "") if "=" in p)
    table = {k.strip().lower(): v.strip() for k, v in table.items()}
    if skill in table:
        return table[skill]
    pool = [s.lower() for s in env["skills"]]
    return table.get("default") if any(skill == s or skill in s.split() for s in pool) else "0"


def m_guarded(env, i, case):
    """The proposed fix: deterministic steps for the two pattern bugs, the live ladder, then the top-k model
    only for a real question (asks with a question mark or a question word), and only a short grounded value."""
    _, kind, label, options, job, _, _ = case
    if _DIAL.search(label):
        m = re.match(r"\s*(\+\d{1,3})", str(env["contact"].get("phone") or ""))
        return m.group(1) if m else None
    if re.search(r"\bhow many years\b", label, re.I):
        return skill_years(env, label)
    value = m_current(env, i, case)
    if value or not ("?" in label or _ASKS.search(label)):
        return value
    value = m_topk(env, i, case)
    return value if value and (value in options or len(value.split()) <= 6) else None


def m_compiled(env, i, case, compiler="local"):
    """Facts told once; the model compiles the question into a plan over fact names; the plan runs deterministically."""
    from career_agent.browser.form_model import Field
    from career_agent.memory import facts as F
    from career_agent.memory.qbank_match import is_junk
    _, kind, label, options, job, _, _ = case
    if is_junk(Field(ref="x", kind=kind, label=label, required=False, options=list(options))):
        env["notes"][i] = "junk label"
        return None
    if "facts" not in env:
        env["facts"] = F.build(env["conn"], env["contact"], env["skills"])
    llm = env["llm"] if compiler == "local" else env.setdefault("haiku", Counted(F.claude_cli_llm("haiku")))
    value, env["notes"][i] = F.answer(label, kind, options, job, env["facts"], llm, cache=env["plans"])
    return value


def m_compiled_haiku(env, i, case):
    """Same facts and executor; Claude Haiku (logged-in CLI, schema only — no values) writes the plans."""
    return m_compiled(env, i, case, compiler="haiku")


METHODS = {"current_nollm": m_current_nollm, "current": m_current, "topk": m_topk,
           "factsheet": m_factsheet, "hybrid": m_hybrid, "guarded": m_guarded, "compiled": m_compiled,
           "compiled_haiku": m_compiled_haiku}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"), help="the data dir (a worktree has none: point at the checkout's)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--methods", default=",".join(METHODS))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = Path(args.data)
    args.db = args.db or str(data / "jobs.db")
    args.out = args.out or str(data / "reports" / "answer_methods_bench.csv")
    from career_agent.memory import qbank
    from career_agent.memory.candidate_profile import load_candidate_profile
    from job_dashboard.apply.store import get_application_profile
    from job_dashboard.letter.draft import make_default_llm

    tmp = Path(tempfile.mkdtemp()) / "jobs.db"
    shutil.copy(args.db, tmp)                           # never touch the real DB
    conn = sqlite3.connect(tmp)
    contact = get_application_profile(conn) or {}
    env = {"conn": conn, "contact": contact, "embed": qbank.default_embed,
           "profile": load_candidate_profile(conn, contact=contact), "llm": Counted(make_default_llm()),
           "notes": {}, "plans": {},
           "skills": json.loads((data / "answer_style" / "ingredients.json").read_text())["skills_pool"]}

    rows, summary = [], {}
    for name in args.methods.split(","):
        fn, stats = METHODS[name], {"correct": 0, "wrong": 0, "missed": 0, "ok_escalate": 0}
        env["llm"].calls, t0 = 0, time.monotonic()
        for i, case in enumerate(CASES):
            try:
                value = fn(env, i, case)
            except Exception as e:                      # a crash is a miss, and says so
                print(f"[{name}] {case[2][:50]!r}: {type(e).__name__}: {e}", file=sys.stderr)
                value = None
            gold = resolve_gold(conn, contact, case[5])
            res = outcome(value, gold, case[6])
            stats[res] += 1
            rows.append({"method": name, "group": case[0], "question": case[2][:90],
                         "answer": "" if value is None else value, "outcome": res,
                         "note": env["notes"].pop(i, "")})
            print(f"{name:14} {res:12} {case[2][:60]!r} -> {value!r}")
        stats["llm_calls"], stats["seconds"] = env["llm"].calls, round(time.monotonic() - t0, 1)
        summary[name] = stats

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(summary, indent=1))
    Path(args.out).with_suffix(".summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
