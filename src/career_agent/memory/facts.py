"""Facts told once; every short question is a plan over them (prototype — not wired into the fill loop).

  fact store   typed, atomic values: profile columns + the bank's own answers, deduplicated (an entry that only
               points at a profile column is the same fact, not a second one). Skills and languages are grids.
  plan         what a question asks, as a small expression over facts: "Are you 18 or older?" ->
               {"op": "cmp", "cmp": ">=", "args": [{"op": "age", "args": [{"fact": "dob"}]}, 18]}
  compiler     the model turns a question into a plan once per wording. It sees fact NAMES and TYPES only, never
               values, so it cannot copy a wrong value; it can say MISSING (ask for the fact) or NOT_A_QUESTION.
  executor     runs the plan deterministically; formatter fits the value to the field (Yes/No, option, number).
Bench: scripts/answer_methods_bench.py --methods compiled."""
from __future__ import annotations

import json
import re
from datetime import date, datetime

LEVELS = ["basic", "conversational", "professional", "fluent", "native"]
# ponytail: static FX table, swap for a live rate if salary questions in other currencies get common
_TO_INR = {"INR": 1.0, "USD": 88.0, "EUR": 102.0, "GBP": 118.0}
_UNIT = {"one": 1, "thousand": 1e3, "lakh": 1e5, "million": 1e6, "crore": 1e7}
_PERIOD = {"year": 1, "month": 12}
_NONE = {"", "no", "none", "n/a", "na", "-"}
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


# ── typed values ─────────────────────────────────────────────────────────────
def money(text):
    """'25 LPA' / '30' (lakhs) / '$4000 per month' -> {amount (in currency units), currency, period}."""
    s = str(text or "").lower().replace(",", "")
    m = re.search(r"\d+(\.\d+)?", s)
    if not m:
        return None
    amt = float(m.group())
    cur = "USD" if ("$" in s or "usd" in s) else "EUR" if "eur" in s else "INR"
    if cur == "INR" and (re.search(r"\blpa\b|lakh|\bl\b", s) or amt < 1000):
        amt *= 1e5                                       # Indian CTCs are quoted in lakhs
    return {"amount": amt, "currency": cur, "period": "month" if "month" in s else "year", "text": str(text)}


def phone(text):
    s = str(text or "").strip()
    m = re.match(r"(\+\d{1,3})[\s-]*(.*)", s)
    return {"dial": m.group(1), "number": re.sub(r"\D", "", m.group(2)), "text": s} if m else \
        {"dial": None, "number": re.sub(r"\D", "", s), "text": s}


def place(text):
    parts = [p.strip() for p in str(text or "").split(",") if p.strip()]
    return {"city": parts[0] if parts else None, "country": parts[-1] if len(parts) > 1 else None, "text": str(text)}


def as_date(text):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(text).strip(), fmt).date()
        except ValueError:
            pass
    return None


def as_list(text):
    items = [x.strip() for x in re.split(r"[,;>]", str(text or "")) if x.strip()]
    return [] if all(x.lower() in _NONE for x in items) else items


def level(text):
    t = str(text or "").strip().lower()
    return next((lv for lv in LEVELS if lv in t), None)


def as_bool(text):
    t = str(text or "").strip().lower()
    return True if t in {"yes", "true", "1", "y"} else False if t in {"no", "false", "0", "n"} else None


# ── fact store ───────────────────────────────────────────────────────────────
def _fact(ftype, value, desc):
    return {"type": ftype, "value": value, "desc": desc}


_PROFILE_TYPES = {"phone": ("phone", phone), "location": ("place", place), "current_ctc": ("money", money),
                  "salary_expectation": ("money", money), "years_experience": ("number", float),
                  "willing_to_relocate": ("bool", lambda v: bool(v)),
                  "notice_period": ("days", lambda v: float(re.search(r"\d+", str(v)).group()))}


def build(conn, contact: dict, skills_pool=()) -> dict:
    """{key: {type, value, desc}} from the profile and the bank. One fact per thing: a bank entry that reads a
    profile column is skipped (the column is the fact); rule entries become the typed fact the rule reads."""
    from . import qbank
    facts = {}
    for k, v in (contact or {}).items():
        if v in (None, "") or k == "updated_at":
            continue
        ftype, conv = _PROFILE_TYPES.get(k, ("text", str))
        facts[k] = _fact(ftype, conv(v), k.replace("_", " "))
    langs = {}
    for e in qbank.entries(conn):
        ans, rule = e.get("answer"), e.get("rule")
        if e.get("topic") == "story" or e.get("profile_ref") or ans in (None, ""):
            continue
        if rule == "years_in_skill":
            table = dict(p.split("=", 1) for p in re.split(r"\s*[,;]\s*", ans) if "=" in p)
            table = {k.strip().lower(): float(v) for k, v in table.items()}
            default = table.pop("default", None)
            grid = {s.lower(): default for s in skills_pool if default is not None}
            grid.update(table)
            facts["skills"] = _fact("map skill->years", grid, "years of experience per skill; a skill not listed is 0")
        elif rule == "company_in_list":
            facts[e["id"]] = _fact("list", as_list(ans), e["question"].replace("this company", "which companies")
                                   + " (companies where the answer is yes; empty = none)")
        elif rule == "preference":
            order, _, refused = ans.partition(";")
            facts[e["id"]] = _fact("list", as_list(order), e["question"] + " (acceptable, best first)")
            if refused.strip():
                facts[e["id"] + "_refused"] = _fact("list", as_list(refused.split(":", 1)[-1]),
                                                    e["question"] + " (refused)")
        elif e["id"] == "date_of_birth":
            facts["dob"] = _fact("date", as_date(ans), "date of birth")
        elif e["id"] == "english_proficiency":
            langs["english"] = level(ans)
        elif e["id"] == "languages_spoken":
            for lang in as_list(ans):
                langs.setdefault(lang.lower(), None)
        elif e["atype"] == "bool":
            facts[e["id"]] = _fact("bool", as_bool(ans), e["question"])
        elif e["atype"] == "number":
            facts[e["id"]] = _fact("number", float(re.search(r"\d+(\.\d+)?", ans).group()), e["question"])
        else:
            facts[e["id"]] = _fact("text", ans, e["question"])
    if langs:
        facts["languages"] = _fact("map language->level", langs,
                                   f"languages spoken and level ({' < '.join(LEVELS)}); null = level not given")
    facts["today"] = _fact("date", date.today(), "today's date")
    return facts


def schema(facts) -> str:
    """What the compiler sees: names, types, descriptions — and the keys of a grid, never a value."""
    out = []
    for k, f in facts.items():
        keys = f" keys={sorted(f['value'])}" if isinstance(f["value"], dict) and f["type"].startswith("map") else ""
        fields = f" fields={[x for x in f['value'] if x != 'text']}" if f["type"] in ("phone", "place", "money") else ""
        out.append(f"{k} ({f['type']}){keys}{fields}: {f['desc']}")
    return "\n".join(out)


# ── executor ─────────────────────────────────────────────────────────────────
class PlanError(Exception):
    pass


def _cmp(a, op, b):
    a, b = (str(x).lower() if isinstance(x, str) else x for x in (a, b))
    return {">=": a >= b, ">": a > b, "<=": a <= b, "<": a < b, "==": a == b, "!=": a != b}[op]


def _contains(hay, needle):
    n = str(needle).lower()
    items = hay if isinstance(hay, list) else [hay]
    return any(n in str(x).lower() or str(x).lower() in n for x in items if x not in (None, ""))


def _money_num(v):
    """Money compares in one unit (INR a year); anything else as it is."""
    if isinstance(v, dict) and "amount" in v and "currency" in v:
        return v["amount"] * _TO_INR[v["currency"]] * _PERIOD[v["period"]]
    return v


def _as_fact_ref(s, facts):
    """Models write a fact as a bare name ("skills") or "phone.dial": read those as references."""
    key, _, field = s.partition(".")
    return {"fact": key, **({"field": field} if field else {})} if key in facts else None


def uses_fact(plan, facts) -> bool:
    if isinstance(plan, str):
        return _as_fact_ref(plan, facts) is not None
    if isinstance(plan, dict):
        return ("fact" in plan or (plan.get("op") == "level_at_least" and "languages" in facts)
                or any(uses_fact(a, facts) for a in plan.get("args", [])))
    return False


def run(plan, facts):
    """Evaluate a plan. Any unknown fact/op or a missing value raises PlanError: never a guessed value."""
    if isinstance(plan, str) and _as_fact_ref(plan, facts):
        plan = _as_fact_ref(plan, facts)
    if not isinstance(plan, dict):
        return plan                                       # a literal (number, string, bool)
    if "fact" in plan:
        f = facts.get(plan["fact"])
        if f is None or f["value"] is None:
            raise PlanError(f"no fact {plan['fact']}")
        v = f["value"]
        if plan.get("field"):
            if not isinstance(v, dict) or v.get(plan["field"]) is None:
                raise PlanError(f"no field {plan['field']} on {plan['fact']}")
            v = v[plan["field"]]
        return v
    op, args = plan.get("op"), [run(a, facts) for a in plan.get("args", [])]
    if op == "age":
        d, t = args[0], facts["today"]["value"]
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))
    if op == "cmp":
        is_money = [isinstance(a, dict) and "currency" in a for a in args[:2]]
        if any(is_money) and not all(is_money):
            raise PlanError("money compared with a bare number: unit unknown")
        return _cmp(_money_num(args[0]), plan["cmp"], _money_num(args[1]))
    if op == "amount":
        unit, cur = plan.get("unit", "one"), plan.get("currency", "INR")
        return {"amount": float(plan["value"]) * _UNIT[unit], "currency": cur, "period": plan.get("period", "year")}
    if op == "lookup":
        m, key = args[0], str(args[1]).lower().strip()
        if not isinstance(m, dict):
            raise PlanError("lookup needs a grid or a record")
        hit = next((v for k, v in m.items() if k == key), None)
        if hit is None:
            hit = next((v for k, v in m.items() if key in k.split() or k in key.split()), None)
        if hit is None and "default" not in plan:
            raise PlanError(f"{key} not in grid")
        return plan.get("default") if hit is None else hit
    if op == "level_at_least":
        langs = (facts.get("languages") or {}).get("value") or {}
        args = [langs.get(str(a).lower(), a) if str(a).lower() in langs else a for a in args]   # a language name
        if args[0] not in LEVELS or level(args[1]) is None:
            raise PlanError("unknown level")
        return LEVELS.index(args[0]) >= LEVELS.index(level(args[1]))
    if op == "money":
        m = args[0]
        inr_year = m["amount"] * _TO_INR[m["currency"]] * _PERIOD[m["period"]]
        cur, per, unit = plan.get("currency", "INR"), plan.get("period", "year"), plan.get("unit", "one")
        return round(inr_year / _TO_INR[cur] / _PERIOD[per] / _UNIT[unit], 2)
    if op == "contains":
        return _contains(args[0], args[1])
    if op == "not":
        return not args[0]
    if op in ("and", "or"):
        return all(args) if op == "and" else any(args)
    raise PlanError(f"unknown op {op}")


# ── formatter ────────────────────────────────────────────────────────────────
_ASKS = re.compile(r"\?|^\s*(are|is|do|does|did|have|has|will|would|can|could|should|were|was)\b", re.I)


def render(value, options=(), label=None):
    """A value in the shape the field takes; None when it fits none of the field's options, or when a yes/no
    result would go into a field that is not a yes/no question ("Pursuing / Completed" wants a word, not Yes)."""
    if isinstance(value, bool):
        yes_no_opts = {o.strip().lower() for o in options} & {"yes", "no", "true", "false"}
        if label is not None and not yes_no_opts and not _ASKS.search(label):
            return None
        text = "Yes" if value else "No"
    elif isinstance(value, float):
        text = str(int(value)) if value == int(value) else str(value)
    elif isinstance(value, dict):
        text = value.get("text") or ", ".join(str(v) for v in value.values() if v)
    elif isinstance(value, list):
        text = ", ".join(map(str, value))
    elif isinstance(value, date):
        text = value.strftime("%d/%m/%Y")
    else:
        text = str(value)
    if not options:
        return text
    from .qbank_match import fit_option
    return fit_option("", text, list(options), None, None)


# ── compiler ─────────────────────────────────────────────────────────────────
OPS_HELP = """Plan language (JSON):
  {"fact": KEY}  or  {"fact": KEY, "field": F}       a stored fact (fields of phone/place/money as listed)
  {"op": "age", "args": [DATE]}                      whole years since a date
  {"op": "cmp", "cmp": ">=|>|<=|<|==|!=", "args": [A, B]}
  {"op": "lookup", "args": [MAP, "key"], "default": 0}   a grid value; give a default only when absent means it
  {"op": "level_at_least", "args": ["english", "fluent"]}   a language's level in the languages grid
  {"op": "money", "args": [MONEY], "currency": "INR|USD|EUR|GBP", "period": "year|month", "unit": "one|thousand|lakh|million"}
  {"op": "amount", "value": 6, "currency": "INR", "unit": "lakh", "period": "year"}   a money amount the form names
  {"op": "contains", "args": [LIST_OR_TEXT, "value"]}
  {"op": "not"|"and"|"or", "args": [...]}            literals (numbers, strings, true/false) are allowed as args

Examples (fact names here are illustrative; use the ones listed above):
  "Are you 18 or older?"            {"plan": {"op": "cmp", "cmp": ">=", "args": [{"op": "age", "args": [{"fact": "dob"}]}, 18]}}
  "Do you live in Germany?"         {"plan": {"op": "cmp", "cmp": "==", "args": [{"fact": "location", "field": "country"}, "Germany"]}}
  "Years of experience in Rust?"    {"plan": {"op": "lookup", "args": [{"fact": "skills"}, "rust"], "default": 0}}
  "Do you speak French fluently?"   {"plan": {"op": "level_at_least", "args": ["french", "fluent"]}}
  "Salary above EUR 4000 a month?"  {"plan": {"op": "cmp", "cmp": ">", "args": [{"fact": "current_ctc"}, {"op": "amount", "value": 4000, "currency": "EUR", "period": "month"}]}}
  "Phone country code"              {"plan": {"fact": "phone", "field": "dial"}}
  "Which language for emails?"      {"plan": "english"}  is WRONG (no fact) — pick from the languages grid only if it is asked about you
  "Secondary email"                 {"missing": {"key": "secondary_email", "type": "text", "ask": "A second email address"}}"""


def claude_cli_llm(model: str = "haiku", timeout: int = 120):
    """llm(prompt) -> text through the logged-in Claude Code CLI (the subscription, not the API). No tools, one turn,
    run from a temp dir so no project instructions load. Raises on a failed call (expired login, timeout)."""
    import subprocess
    import tempfile

    def llm(prompt: str) -> str:
        r = subprocess.run(["claude", "-p", "--model", model, "--max-turns", "1", "--tools", "",
                            "--system-prompt", "You translate job-application form fields into JSON plans. "
                                               "Reply with JSON only."],
                           input=prompt, capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir())
        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError((r.stderr or r.stdout or "claude -p failed").strip()[:200])
        return r.stdout
    return llm


def compile_question(question, kind, options, job, facts, llm) -> dict:
    """{'plan': expr} | {'missing': {'key', 'type', 'ask'}} | {'not_a_question': True} | {} on a bad reply."""
    opt = f"\nIts options: {list(options)}" if options else ""
    prompt = (
        "You translate a job-application form field into a plan over the candidate's stored facts. You see the "
        "facts' names and types, not their values; the plan is executed later.\n\n"
        f"Job: {job.get('company') or '?'} ({job.get('location') or '?'})\nField ({kind}): {question}{opt}\n\n"
        f"Stored facts:\n{schema(facts)}\n\n{OPS_HELP}\n\n"
        "Rules: a yes/no question must yield true/false. Use ONLY facts that answer what is asked. A general fact "
        "answers a narrower version of it: a stored non-compete answer covers 'that would affect your work at "
        "<company>'; per-company lists answer the question for this job's company; the phone answers 'mobile' or "
        "'WhatsApp number'; an availability, preference or location list answers a yes/no about willingness (combine "
        "with and). A DIFFERENT quantity is missing: an alternate/second number is not the phone, a percentage is not "
        "a CGPA, a confidentiality/IP agreement is not a non-compete. Experience in a skill not in the skills grid is "
        "0 (lookup with default 0).\n"
        'Reply with JSON only, one of:\n{"plan": ...}\n{"missing": {"key": "snake_case", "type": "bool|number|text|'
        'date|money", "ask": "the fact to ask the candidate, once"}}\n{"not_a_question": true}   (a captcha, a '
        "search box, a placeholder, an unreadable label)")
    try:
        reply = _THINK.sub("", llm(prompt) or "")
        obj, _ = json.JSONDecoder().raw_decode(reply[reply.find("{"):])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def answer(question, kind, options, job, facts, llm, cache=None):
    """(value or None, note). The plan is cached per wording: the model runs once per new phrasing."""
    from .qbank import norm
    key = norm(question)
    out = cache.get(key) if cache is not None else None
    if out is None:
        out = compile_question(question, kind, options, job, facts, llm)
        if cache is not None:
            cache[key] = out
    if "not_a_question" in out:
        return None, "not a question"
    if "missing" in out:
        return None, f"MISSING {json.dumps(out['missing'])}"
    if "plan" not in out:
        return None, "no plan"
    if not uses_fact(out["plan"], facts):
        return None, f"plan uses no stored fact | {json.dumps(out['plan'])}"     # a constant is a guess
    try:
        value = run(out["plan"], facts)
    except (PlanError, KeyError, TypeError, ValueError, AttributeError) as e:
        return None, f"plan failed: {e} | {json.dumps(out['plan'])}"
    text = render(value, options, label=None if kind == "checkbox" else question)    # a tick box is a yes/no field
    if text is None:
        return None, f"yes/no result does not fit this field | {json.dumps(out['plan'])}"
    return text, json.dumps(out["plan"])
