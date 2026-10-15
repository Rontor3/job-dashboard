"""plans_first: persisted plans tried BEFORE the bank.

  plan store   sqlite in env conn (temp copy): plan(id=sha1 canonical json, plan_json, out_type)
               + plan_wording(norm, plan_id, vec, text). Optionally preloaded from plans_first_store.json
               (written only with PLANS_FIRST_SAVE=1) — the "persisted across runs" part.
  lookup       exact norm, else MiniLM nearest >= HIGH with the same out_type, no qualifier/polarity clash, and
               every literal the plan names (skill, number, company, currency) present in the new question/job.
  miss         Haiku compiles (schema only, never values), persisted. NEW_FACT / Haiku down / bad reply -> m_guarded.
  render       facts.render, plus: a bool into a non-yes/no field picks the field's own words (Pursuing/Completed)
               by the plan's fact name, else escalates; days render with a unit so option buckets fit."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
from career_agent.memory import facts as F                       # noqa: E402
from career_agent.memory import qbank                            # noqa: E402
from career_agent.memory.qbank_match import _polarity, is_junk, qualifier_clash   # noqa: E402

HIGH = 0.87
STORE = Path(__file__).resolve().with_name("plans_first_store.json")
_SKIP_KEYS = {"op", "cmp", "default", "fact", "field", "period", "unit"}
_YN = {"yes", "no", "true", "false"}


def _bench():
    if "answer_methods_bench" not in sys.modules:
        import importlib.util
        spec = importlib.util.spec_from_file_location("answer_methods_bench", REPO / "scripts" / "answer_methods_bench.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["answer_methods_bench"] = mod
    return sys.modules["answer_methods_bench"]


def setup(env):
    c = env["conn"]
    c.execute("CREATE TABLE IF NOT EXISTS plan (id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, out_type TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS plan_wording (norm TEXT PRIMARY KEY, plan_id TEXT NOT NULL, vec BLOB, text TEXT)")
    c.commit()
    env["pf_haiku_fail"] = 0
    if STORE.exists():
        for row in json.loads(STORE.read_text()):
            _persist(env, row["text"], row["out"], row["out_type"], save=False)


def out_type(kind, label, options):
    opts = {o.strip().lower() for o in options}
    if kind == "checkbox" or (opts and opts <= _YN) or (not opts and F._YES_NO_Q.search(label or "")):
        return "bool"
    if opts:
        return "choice"
    return "number" if re.search(r"\bhow many\b|\bnumber of\b|\byears\b", label or "", re.I) else "text"


def _persist(env, text, out, otype, save=True):
    pj = json.dumps(out, sort_keys=True, separators=(",", ":"))
    pid = hashlib.sha1(pj.encode()).hexdigest()
    c = env["conn"]
    c.execute("INSERT OR IGNORE INTO plan VALUES (?,?,?)", (pid, pj, otype))
    vec = np.asarray(env["embed"]([text])[0], dtype="float32").tobytes()
    c.execute("INSERT OR REPLACE INTO plan_wording VALUES (?,?,?,?)", (qbank.norm(text), pid, vec, text))
    c.commit()
    if save and os.environ.get("PLANS_FIRST_SAVE") == "1":
        rows = json.loads(STORE.read_text()) if STORE.exists() else []
        rows = [r for r in rows if qbank.norm(r["text"]) != qbank.norm(text)]
        STORE.write_text(json.dumps(rows + [{"text": text, "out": out, "out_type": otype}], indent=1))


def literals(plan, facts) -> list[str]:
    """Strings/numbers a plan names that are not fact references (skill, threshold, company, currency)."""
    out = []
    if isinstance(plan, dict):
        for k, v in plan.items():
            if k in _SKIP_KEYS:
                continue
            if k == "currency" and v != "INR":
                out.append(str(v))
            elif k == "value":
                out.append(v)
            elif k == "args":
                out.extend(x for a in v for x in literals(a, facts))
            elif k == "plan":
                out.extend(literals(v, facts))
    elif isinstance(plan, bool):
        pass
    elif isinstance(plan, (int, float)):
        out.append(plan)
    elif isinstance(plan, str) and not F._as_fact_ref(plan, facts) and plan.lower() not in F.LEVELS:
        out.append(plan)
    return out


def _literals_fit(plan, facts, question, job) -> bool:
    hay = " ".join([question, str(job.get("company") or ""), str(job.get("location") or "")]).lower()
    nums = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", hay.replace(",", ""))}
    for lit in literals(plan, facts):
        if isinstance(lit, (int, float)):
            if float(lit) not in nums:
                return False
        elif str(lit).lower() not in hay and not (str(lit).upper() == "USD" and "$" in hay):
            return False
    return True


def lookup(env, question, otype, job):
    c, key = env["conn"], qbank.norm(question)
    r = c.execute("SELECT p.plan_json FROM plan_wording w JOIN plan p ON p.id=w.plan_id WHERE w.norm=?", (key,)).fetchone()
    if r:
        return json.loads(r[0]), "exact"
    rows = c.execute("SELECT w.text, w.vec, p.plan_json, p.out_type FROM plan_wording w JOIN plan p ON p.id=w.plan_id").fetchall()
    if not rows:
        return None, None
    q = env["embed"]([question])[0]
    sims = np.stack([np.frombuffer(v, dtype="float32") for _, v, _, _ in rows]) @ q
    for j in np.argsort(-sims):
        text, _, pj, ot = rows[j]
        if sims[j] < HIGH:
            break
        out = json.loads(pj)
        if (ot == otype and not qualifier_clash(question, text) and _polarity(question) == _polarity(text)
                and _literals_fit(out.get("plan"), env["facts"], question, job)):
            return out, f"reuse {sims[j]:.2f} '{text[:40]}'"
    return None, None


def _fact_words(plan) -> set:
    s = json.dumps(plan)
    return {w for k in re.findall(r'"fact":\s*"([^"]+)"', s) for w in re.split(r"[_\W]+", k.lower()) if len(w) > 3}


def bool_to_words(value, plan, label, options):
    """True/False into a field that wants words: its options, else the label's 'A / B' alternatives. The word
    sharing a stem with the plan's fact name is the True side; no such word -> None (escalate)."""
    alts = list(options) or [a.strip(" *:") for a in re.split(r"/|\bor\b", label or "") if a.strip(" *:")]
    if len(alts) != 2:
        return None
    words = _fact_words(plan)
    hit = [a for a in alts if any(w[:5] in a.lower() for w in words)]
    if len(hit) != 1:
        return None
    return hit[0] if value else next(a for a in alts if a != hit[0])


def render(env, out, kind, label, options):
    plan, facts = out["plan"], env["facts"]
    value = F.run(plan, facts)
    if isinstance(value, float) and isinstance(plan, dict) and facts.get(plan.get("fact"), {}).get("type") == "days":
        value = f"{int(value)} days"                       # a unit lets option buckets ("30 Days", "1 Month") fit
    text = F.render(value, options, label=None if kind == "checkbox" else label, hint=label)
    if text is None and isinstance(value, bool):
        text = bool_to_words(value, plan, label, options)
    if text and not options and kind != "checkbox" and F._YES_NO_Q.search(label or "") and len(text.split()) > 6:
        return None
    return text


def answer(env, i, case):
    from career_agent.browser.form_model import Field
    _, kind, label, options, job, _, _ = case
    if is_junk(Field(ref="x", kind=kind, label=label, required=False, options=list(options))) \
            or F._OPTION_RUN.fullmatch((label or "").strip()):
        env["notes"][i] = "junk"
        return None
    otype = out_type(kind, label, options)
    out, how = lookup(env, label, otype, job)
    if out is None:
        failed = []

        def llm(p):
            try:
                return env["haiku"](p)
            except Exception as e:
                failed.append(e)
                raise
        out, how = F.compile_question(label, kind, options, job, env["facts"], llm), "haiku"
        if failed or not out or not ({"plan", "missing", "not_a_question"} & set(out)):
            env["pf_haiku_fail"] += bool(failed)
            env["notes"][i] = f"compile failed ({failed[:1]}) -> guarded"
            return _bench().m_guarded(env, i, case)
        if "plan" in out and not F.uses_fact(out["plan"], env["facts"]):
            env["notes"][i] = "constant plan -> escalate"
            return None
        _persist(env, label, out, otype)
    if "not_a_question" in out:
        env["notes"][i] = f"{how}: not a question"
        return None
    if "missing" in out:
        v = _bench().m_guarded(env, i, case)
        env["notes"][i] = f"{how}: MISSING {out['missing'].get('key')} -> guarded {'hit' if v else 'none'}"
        return v
    try:
        text = render(env, out, kind, label, options)
    except (F.PlanError, KeyError, TypeError, ValueError, AttributeError) as e:
        env["notes"][i] = f"{how}: plan failed {e} -> escalate"   # a plan that fails its checks fills nothing
        return None
    env["notes"][i] = f"{how}: {json.dumps(out['plan'])[:200]}"
    return text


if __name__ == "__main__":                                 # self-check for the pure helpers
    fx = {"degree_completed": {"type": "bool", "value": True}, "skills": {"type": "map", "value": {}}}
    p = {"fact": "degree_completed"}
    assert bool_to_words(True, p, "Pursuing/ Completed *", []) == "Completed"
    assert bool_to_words(False, p, "Pursuing/ Completed *", []) == "Pursuing"
    assert bool_to_words(True, {"fact": "x_y"}, "Pursuing/ Completed *", []) is None
    sp = {"op": "lookup", "args": [{"fact": "skills"}, "python"], "default": 0}
    assert _literals_fit(sp, fx, "Years in Python?", {}) and not _literals_fit(sp, fx, "Years in Linux?", {})
    mp = {"op": "cmp", "cmp": ">", "args": [{"fact": "current_ctc"}, {"op": "amount", "value": 3500, "currency": "USD"}]}
    assert _literals_fit(mp, fx, "Salary above USD 3500?", {}) and not _literals_fit(mp, fx, "Salary above USD 4000?", {})
    assert _literals_fit(mp, fx, "Salary above $3500?", {})
    print("ok")
