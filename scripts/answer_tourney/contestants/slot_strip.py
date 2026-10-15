"""slot_strip: fully local. Slots (skill, company, place, number, money) are replaced by placeholders on both the
question and every bank wording; the stripped question is matched exact, then by MiniLM, with hard vetoes
(qualifier, polarity, field shape). The matched entry's rule/answer runs on the RAW question. Comparisons
(salary above X, notice within N days, N+ years of age) are small deterministic parsers over facts.build values.
Anything else falls back to the bench's m_guarded."""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

_bench = sys.modules.get("answer_methods_bench")
if _bench is None:                                     # imported outside run.py
    import importlib.util
    _p = Path(__file__).resolve().parents[2] / "answer_methods_bench.py"
    _s = importlib.util.spec_from_file_location("answer_methods_bench", _p)
    _bench = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(_bench)

HIGH, MARGIN = 0.80, 0.03                              # stripped-text cosine; tuned on the old 44 only
LOW, WIDE = 0.70, 0.15                                 # or: a weaker top that leads by a wide margin
_PLACES = ["india", "united states", "usa", "us", "uk", "united kingdom", "germany", "canada", "singapore",
           "europe", "bengaluru", "bangalore", "gurugram", "gurgaon", "mumbai", "pune", "hyderabad", "chennai",
           "delhi", "noida", "kolkata", "london", "new york"]
_MONEY_TOK = r"(?:usd|inr|eur|gbp|rs\.?|\$|₹|€|£)"
_YN_Q = re.compile(r"^\s*(are|is|do|does|did|have|has|will|would|can|could|should|were|was)\b", re.I)
_PHONE = re.compile(r"\b(whats ?app|mobile|cell|phone|contact)\s*(no|number|#)?\b", re.I)
_OTHER_PHONE = re.compile(r"\b(alternate|alternative|secondary|second|other|emergency|home|office|landline|reference|type|code)\b", re.I)
_WH_Q = re.compile(r"^\s*(how|what|which|when|where|why|enter|please (enter|provide|specify))\b", re.I)


def _slot_vocab(env):
    from career_agent.memory import qbank
    table = (qbank.get_entry(env["conn"], "skill_years") or {}).get("answer") or ""
    skills = {s.strip().lower() for s in env["skills"]} | {p.split("=")[0].strip().lower()
                                                            for p in re.split(r"[,;]", table) if "=" in p}
    skills = sorted((s for s in skills if len(s) > 2 and s != "default"), key=len, reverse=True)
    loc = str(env["contact"].get("location") or "")
    places = {p.strip().lower() for p in loc.split(",") if p.strip()} | set(_PLACES)
    return skills, sorted(places, key=len, reverse=True)


def strip(text, env, job=None):
    s = " " + (text or "").lower() + " "
    company = ((job or {}).get("company") or "").strip().lower()
    if company:
        s = re.sub(rf"(?<!\w){re.escape(company)}(?!\w)", " {company} ", s)
    s = re.sub(r"\b(this|the|our|your|a|that) (company|organi[sz]ation|employer)\b", " {company} ", s)
    s = re.sub(rf"{_MONEY_TOK}\s*\d[\d,.]*|\d[\d,.]*\s*(?:lpa|lakhs?|lacs?|k\b|{_MONEY_TOK})", " {money} ", s)
    s = re.sub(r"\d+(?:\.\d+)?", " {n} ", s)
    skills, places = env["_slots"]
    for p in places:
        s = re.sub(rf"(?<!\w){re.escape(p)}(?!\w)", " {place} ", s)
    for k in skills:
        s = re.sub(rf"(?<!\w){re.escape(k)}(?!\w)", " {skill} ", s)
    s = re.sub(r"[^\w{} ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def setup(env):
    import numpy as np
    from career_agent.memory import qbank
    env["_slots"] = _slot_vocab(env)
    rows = env["conn"].execute(
        "SELECT COALESCE(w.text, w.norm), w.entry_id FROM qbank_wording w JOIN qbank_entry e ON e.id=w.entry_id "
        "WHERE e.status='active' AND e.topic IS NOT 'story'").fetchall()
    texts = [t for t, _ in rows]
    stripped = [strip(t, env) for t in texts]
    env["_wd"] = {"text": texts, "eid": [e for _, e in rows], "strip": stripped,
                  "vec": np.asarray(env["embed"](stripped)) if stripped else None}


# ── deterministic comparisons over facts ─────────────────────────────────────
def _inr_year(m):
    from career_agent.memory import facts as F
    return m["amount"] * F._TO_INR[m["currency"]] * F._PERIOD[m["period"]]


def _named_money(label):
    from career_agent.memory import facts as F
    m = re.search(rf"({_MONEY_TOK}\s*\d[\d,.]*\s*(?:k|lpa|lakhs?|lacs?)?(?:\s*(?:per|a|/)\s*(?:month|year|annum))?"
                  rf"|\d[\d,.]*\s*(?:k\b|lpa|lakhs?|lacs?|{_MONEY_TOK})(?:\s*(?:per|a|/)\s*(?:month|year|annum))?)", label, re.I)
    if not m:
        return None
    txt = m.group(1)
    mo = F.money(re.sub(r"(\d)\s*k\b", r"\g<1>000", txt, flags=re.I))
    if mo and mo["currency"] != "INR" and "year" not in txt.lower() and "annum" not in txt.lower() and mo["amount"] < 20000:
        mo["period"] = "month"                         # "$3500" with no period: a monthly figure
    return mo


def _yn(b, options):
    from career_agent.memory.qbank_match import fit_option
    v = "Yes" if b else "No"
    return fit_option("", v, options, None) if options else v


def compare(env, label, options):
    f = {k: v["value"] for k, v in env["facts"].items()}
    low = label.lower()
    yn_field = not options or {o.strip().lower() for o in options} <= {"yes", "no"}
    if not yn_field:
        return None
    m = re.search(r"(\d+)\s*(?:\+|years?)?\s*(?:years? )?(?:of age|years old)[^?]*?(or older|or above|or over|\+)?", low)
    if m and f.get("dob") and ("older" in low or "above" in low or "over" in low or "+" in low or "at least" in low):
        d, t = f["dob"], date.today()
        return _yn(t.year - d.year - ((t.month, t.day) < (d.month, d.day)) >= int(m.group(1)), options)
    named = _named_money(label)
    if named:
        if re.search(r"\b(expect|okay with|ok with|fine with|accept|willing|comfortable|offer)", low):
            mine, up = f.get("salary_expectation"), True      # an offer of X: fine if X reaches what I expect
        elif re.search(r"\b(current|present|drawing|existing|earn)", low):
            mine, up = f.get("current_ctc"), False
        else:
            return None
        if not isinstance(mine, dict):
            return None
        a, b = _inr_year(mine), _inr_year(named)
        if up:
            return _yn(b >= a, options)
        if re.search(r"\b(above|more than|over|greater|exceed|at least)\b", low):
            return _yn(a > b, options)
        if re.search(r"\b(below|less than|under|up to|upto|within)\b", low):
            return _yn(a <= b, options)
        return None
    m = re.search(r"\b(within|under|less than|in|up to|before)\s+(\d+)\s*(day|week|month)s?", low)
    if m and re.search(r"\b(notice|join|start|available)", low) and f.get("notice_period") is not None:
        lim = int(m.group(2)) * {"day": 1, "week": 7, "month": 30}[m.group(3)]
        return _yn(f["notice_period"] <= lim, options)
    if re.search(r"\b(join|start)\b.*\bimmediately\b|\bimmediate joiner", low) and f.get("notice_period") is not None:
        return _yn(f["notice_period"] <= 0, options)
    return None


# ── slot-stripped bank match ─────────────────────────────────────────────────
def _shape_clash(kind, label, options, entry, value):
    opts = {o.strip().lower() for o in options}
    yn_val = str(value).strip().lower() in {"yes", "no", "true", "false"}
    if kind == "checkbox":
        return not yn_val
    if opts and opts <= {"yes", "no"}:
        return not yn_val and entry.get("atype") != "bool"
    if not opts and _YN_Q.search(label) and not yn_val:
        return True                                    # a yes/no question got a non-yes/no value
    if _WH_Q.search(label) and yn_val:
        return True                                    # "what/how many" got Yes/No
    return False


def bank_match(env, kind, label, options, job):
    import numpy as np
    from career_agent.memory import qbank
    from career_agent.memory.qbank_match import _polarity, qualifier_clash, resolve_value, fit_option, split_escape
    question, escape = split_escape(label)
    sq = strip(question, env, job)
    wd = env["_wd"]
    if not sq or wd["vec"] is None:
        return None, "empty"
    hits = {wd["eid"][j] for j, s in enumerate(wd["strip"]) if s == sq}
    if len(hits) == 1:
        eid, how = hits.pop(), "exact"
        text = next(t for t, e, s in zip(wd["text"], wd["eid"], wd["strip"]) if e == eid and s == sq)
    else:
        sims = wd["vec"] @ env["embed"]([sq])[0]
        best = {}
        for j in np.argsort(-sims):
            best.setdefault(wd["eid"][j], (float(sims[j]), wd["text"][j]))
            if len(best) == 2:
                break
        (eid, (s1, text)), *rest = best.items()
        s2 = rest[0][1][0] if rest else 0.0
        if not ((s1 >= HIGH and s1 - s2 >= MARGIN) or (s1 >= LOW and s1 - s2 >= WIDE)):
            return None, f"weak {eid}:{s1:.2f}/{s2:.2f}"
        how = f"mini {s1:.2f}"
    if qualifier_clash(question, text) or _polarity(question) != _polarity(text):
        return None, f"veto qualifier/polarity vs {eid}"
    entry = qbank.get_entry(env["conn"], eid)
    if entry is None or entry.get("rule") == "years_in_skill":
        return None, f"skip {eid}"
    value = resolve_value(env["conn"], entry, question=question, escape=escape, job=job,
                          contact=env["contact"], options=options)
    if value in (None, ""):
        return None, f"{eid} no value"
    if _shape_clash(kind, label, options, entry, value):
        return None, f"veto shape {eid}"
    fitted = fit_option(label, value, options, entry.get("synonyms"))
    return fitted, f"{how} {eid}"


def answer(env, i, case):
    from career_agent.memory.qbank_match import is_junk
    _, kind, label, options, job, _, _ = case
    if "_wd" not in env:
        setup(env)
    if is_junk(_bench.field(i, kind, label, options)):
        env["notes"][i] = "junk"
        return None
    if _bench._DIAL.search(label) or re.search(r"\bhow many years\b", label, re.I):
        env["notes"][i] = "guarded rule"
        return _bench.m_guarded(env, i, case)
    if (_PHONE.search(label) and not _OTHER_PHONE.search(label) and not options
            and not _YN_Q.search(label) and env["contact"].get("phone")):
        env["notes"][i] = "phone by shape"
        return str(env["contact"]["phone"])
    v = compare(env, label, options)
    if v is not None:
        env["notes"][i] = "compare"
        return v
    v, note = bank_match(env, kind, label, options, job)
    if v not in (None, ""):
        env["notes"][i] = f"slot {note}"
        return v
    env["notes"][i] = f"guarded ({note})"
    return _bench.m_guarded(env, i, case)


if __name__ == "__main__":                              # tiny self-check of the parsers (no DB)
    e = {"_slots": (["python", "sql"], ["india", "bengaluru"])}
    assert strip("Years of Python at Acme in India?", e, {"company": "Acme"}) == "years of {skill} at {company} in {place}"
    assert strip("Salary above USD 3,500?", e) == "salary above {money}"
    m = _named_money("Is your Current Salary Above USD 3500?")
    assert m["currency"] == "USD" and m["period"] == "month" and m["amount"] == 3500
    assert _named_money("okay with up to 6 LPA?")["amount"] == 6e5
    assert _PHONE.search("WhatsApp Number") and _OTHER_PHONE.search("Alternate Number")
    print("ok")
