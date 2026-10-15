"""Facts told once; every short question is a plan over them (wired in through factcards.py).

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
from datetime import date, datetime, timedelta

from .fact_units import fit_unit, window_option as _window_option

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
    parts = str((contact or {}).get("full_name") or "").split()
    if len(parts) >= 2:                                   # forms split the name; it is still one fact
        facts.setdefault("first_name", _fact("text", parts[0], "first / given name"))
        facts.setdefault("last_name", _fact("text", parts[-1], "last / family name / surname"))
        if len(parts) > 2:
            facts.setdefault("middle_name", _fact("text", " ".join(parts[1:-1]), "middle name"))
    langs, regions, derived = {}, {}, dict(DERIVED)
    for e in qbank.entries(conn):
        ans, rule = e.get("answer"), e.get("rule")
        if rule == "preference" and isinstance(e.get("synonyms"), dict):
            for region, members in e["synonyms"].items():
                regions.setdefault(region, []).extend(members)
        if rule == "derived" and isinstance(e.get("slots"), dict):
            derived[e["id"]] = (e["atype"], e["question"], e["slots"])      # a formula told once, at run time
            continue
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
        elif e["atype"] == "date" and as_date(ans):
            facts[e["id"]] = _fact("date", as_date(ans), e["question"])
        else:
            facts[e["id"]] = _fact("text", ans, e["question"])
    if langs:
        facts["languages"] = _fact("map language->level", langs,
                                   f"languages spoken and level ({' < '.join(LEVELS)}); null = level not given")
    if regions:
        facts["place_regions"] = _fact("map region->places", regions, "cities/states inside each region")
    facts["today"] = _fact("date", date.today(), "today's date")
    facts.setdefault("join_buffer_days", _fact("number", JOIN_BUFFER_DAYS,
                                               "days needed after the notice period ends before joining"))
    for key, (ftype, desc, plan) in derived.items():      # computed every run: never stored, never stale
        try:
            facts[key] = _fact(ftype, run(plan, facts), f"{desc} (computed)")
        except (PlanError, KeyError, TypeError, ValueError):
            pass                                          # a base fact it needs is not told yet
    return facts


JOIN_BUFFER_DAYS = 15.0      # same for everyone; a stored join_buffer_days fact overrides it
# Derived facts: formulas over base facts, defined once (no personal value here — base facts hold those).
DERIVED = {
    "earliest_start": ("date", "earliest possible start / joining date: today + notice period + joining buffer",
                       {"op": "add_days", "args": [{"fact": "today"}, {"fact": "notice_period"},
                                                   {"fact": "join_buffer_days"}]}),
    "last_working_day": ("date", "last working day at the current employer: today + notice period",
                         {"op": "add_days", "args": [{"fact": "today"}, {"fact": "notice_period"}]}),
    "days_to_join": ("days", "days from an offer until you can join: notice period + joining buffer",
                     {"op": "add_days", "args": [{"fact": "notice_period"}, {"fact": "join_buffer_days"}]}),
    "experience_months": ("number", "total work experience in months, since the career start",
                          {"op": "months_between", "args": [{"fact": "career_start"}, {"fact": "today"}]}),
}


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


def _contains(hay, needle, regions=None):
    """Substring either way, or the needle is a place inside a listed region ('Gurugram' in ['India'])."""
    n = str(needle).lower()
    items = [x for x in (hay if isinstance(hay, list) else [hay]) if x not in (None, "")]
    if any(n in str(x).lower() or str(x).lower() in n for x in items):
        return True
    regions = {k.lower(): v for k, v in (regions or {}).items()}
    return any(re.search(rf"\b{re.escape(m)}\b", n) for x in items for m in regions.get(str(x).lower(), []))


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
        return _contains(args[0], args[1], (facts.get("place_regions") or {}).get("value"))
    if op == "add_days":                                  # a date plus days, or day counts summed
        if not all(isinstance(a, (int, float)) for a in args[1:]) or not isinstance(args[0], (date, int, float)):
            raise PlanError("add_days needs a date (or days) then day counts")
        return args[0] + timedelta(days=sum(args[1:])) if isinstance(args[0], date) else float(sum(args))
    if op == "months_between":
        a, b = args[:2]
        if not (isinstance(a, date) and isinstance(b, date)):
            raise PlanError("months_between needs two dates")
        months = (b.year - a.year) * 12 + b.month - a.month - (b.day < a.day)
        return round(months / 12, 1) if plan.get("unit") == "year" else float(months)
    if op == "not":
        return not args[0]
    if op in ("and", "or"):
        return all(args) if op == "and" else any(args)
    raise PlanError(f"unknown op {op}")


# ── formatter ────────────────────────────────────────────────────────────────
_ASKS = re.compile(r"\?|^\s*(are|is|do|does|did|have|has|will|would|can|could|should|were|was)\b", re.I)


_YES_NO_Q = re.compile(r"^\s*(are|is|do|does|did|have|has|will|would|can|could|were|was)\b|^\s*\w+(\s+\w+){0,3}\?\s*$", re.I)
_OPTION_RUN = re.compile(r"(?:[A-Z][a-z]{1,8}|\d{1,4}){4,}")     # "JanFebMar...": options glued into a label
_AMOUNT = re.compile(r"amount|₹|\binr\b|rupee|in rs\b|annual (salary|ctc) in", re.I)
_LAKH = re.compile(r"lakh|\blpa\b|\blac\b", re.I)


def _money_text(m: dict, hint: str) -> str:
    """Money in the unit the FIELD wants: lakhs when it says so, a plain amount for an amount box (Keka's
    currentSalary.amount next to its own currency dropdown), else the stored wording ('25 LPA')."""
    if _LAKH.search(hint):
        return render(round(m["amount"] / 1e5, 2))
    if _AMOUNT.search(hint):
        return render(float(round(m["amount"])))
    return m.get("text") or render(float(m["amount"]))


def render(value, options=(), label=None, hint=""):
    """A value in the shape the field takes; None when it fits none of the field's options, or when a yes/no
    result would go into a field that is not a yes/no question ("Pursuing / Completed" wants a word, not Yes).
    `hint` = the field's label + name/ref + input type, read for the unit a money field wants."""
    if isinstance(value, bool):
        want = {"yes", "y", "true", "t"} if value else {"no", "n", "false", "f"}
        own = [o for o in options if o.strip().lower() in want]
        if own:
            return own[0]                                 # the field's own words: Y/N, True/False
        yes_no_opts = {o.strip().lower() for o in options} & {"yes", "no", "true", "false", "y", "n"}
        if label is not None and not yes_no_opts and not _ASKS.search(label):
            return None
        text = "Yes" if value else "No"
    elif isinstance(value, (int, float)) and options and (pick := _window_option(value, options)):
        return pick
    elif isinstance(value, float):
        text = str(int(value)) if value == int(value) else str(value)
    elif isinstance(value, dict) and "amount" in value and "currency" in value:
        text = _money_text(value, hint or label or "")
    elif isinstance(value, dict) and "text" not in value:
        # a grid (skills -> years, languages -> level): the field wants the NAMES (live Keka bug wrote '3.0, 2.0, ...')
        text = ", ".join(k for k, v in value.items() if v not in (None, 0, 0.0, "", False))
    elif isinstance(value, dict):
        text = value["text"]
    elif isinstance(value, list):
        text = ", ".join(map(str, value))
    elif isinstance(value, date) and re.search(r"\byear\b", f"{label} {hint}", re.I) \
            and not re.search(r"\b(date|dd|mm|month)\b", f"{label} {hint}", re.I):
        text = str(value.year)                            # "Year of birth": the year, not the whole date
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
  {"op": "contains", "args": [LIST_OR_TEXT, "value"]}   a place counts as inside a listed region (Gurugram in India)
  {"op": "add_days", "args": [DATE, DAYS, ...]}       a date plus day counts (or day counts summed)
  facts of type days are in DAYS: the formatter converts them when the field asks for weeks or months
  {"op": "months_between", "args": [DATE, DATE], "unit": "month|year"}
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


def claude_cli_llm(model: str = "haiku", timeout: int = 120,
                   system: str = "You translate job-application form fields into JSON plans. Reply with JSON only."):
    """llm(prompt) -> text through the logged-in Claude Code CLI (the subscription, not the API). No tools, one turn,
    run from a temp dir so no project instructions load. Raises on a failed call (expired login, timeout)."""
    import subprocess
    import tempfile

    def llm(prompt: str) -> str:
        r = subprocess.run(["claude", "-p", "--model", model, "--max-turns", "1", "--tools", "",
                            "--system-prompt", system],
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
        "A value about the candidate that is COMPUTED from stored facts (a date, a duration, a count) and is not "
        "yet a stored fact: reply derive, naming it so every later wording reuses it. MISSING only for what "
        "cannot be computed; never a fact about this one application (how you found this job, dates of one "
        "work-history row, your opinion of this role) — that is not_a_question.\n"
        'Reply with JSON only, one of:\n{"plan": ...}\n{"derive": {"key": "snake_case", "type": "date|number|bool|'
        'text", "desc": "what it is, generic (no company name)", "plan": ...}}\n{"missing": {"key": "snake_case", '
        '"type": "bool|number|text|date|money", "ask": "the fact to ask the candidate once, generic (no company '
        'name)"}}\n{"not_a_question": true}   (a captcha, a search box, a placeholder, an unreadable label, a '
        "one-application detail)")
    reply = _THINK.sub("", llm(prompt) or "")             # a failed call raises: the caller fails closed
    try:
        obj, _ = json.JSONDecoder().raw_decode(reply[reply.find("{"):])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def answer(question, kind, options, job, facts, llm, cache=None, hint=""):
    """(value or None, note). The plan is cached per wording: the model runs once per new phrasing. `hint`: the
    field's name/ref/input type, read by the formatter (the unit a money box wants)."""
    from .qbank import norm
    if _OPTION_RUN.fullmatch((question or "").strip()):
        return None, "unreadable label (a run of option words)"      # live Keka: "JanFeb...Dec" got the birth year
    key = norm(question)
    out = cache.get(key) if cache is not None else None
    if out is None:
        out = compile_question(question, kind, options, job, facts, llm)
        if cache is not None:
            cache[key] = out
    derive = out.get("derive") if isinstance(out.get("derive"), dict) else None
    if derive:                                            # a new derived fact: answered now, saved by the caller
        out = {"plan": derive.get("plan")}
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", str(derive.get("key") or "")) or derive["key"] in facts:
            derive = None                                 # a bad or taken name: still a plan, just not saved
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
    ref = _as_fact_ref(out["plan"], facts) if isinstance(out["plan"], str) else out["plan"]
    ftype = facts.get(ref.get("fact"), {}).get("type") if isinstance(ref, dict) and set(ref) == {"fact"} else None
    value = fit_unit(value, ftype, facts["today"]["value"], f"{question} {hint}")
    text = render(value, options, label=None if kind == "checkbox" else question,    # a tick box is a yes/no field
                  hint=f"{question} {hint}")
    if text and not options and kind != "checkbox" and _YES_NO_Q.search(question or "") and len(text.split()) > 6:
        return None, f"a yes/no question got a sentence | {json.dumps(out['plan'])}"   # Worksbot 'Authorized to work?'
    if text is None:
        return None, f"yes/no result does not fit this field | {json.dumps(out['plan'])}"
    return text, (f"DERIVE {json.dumps(derive)}" if derive else json.dumps(out["plan"]))

