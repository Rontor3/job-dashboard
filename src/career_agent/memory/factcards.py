"""Two readers over the fact sheet; a short field is filled only when they agree.

  cards    one per fact from facts.build (base + derived), searched by "key: description" — never by value
  local    the local model reads the top cards WITH values and must cite one; deterministic checks follow
           (cited card was retrieved, option fit, yes/no shape, value found in that card)
  haiku    facts.answer: a plan written from the fact schema only (no values leave the machine), run locally
  gate     agree -> fill | local had nothing -> the checked plan alone | disagree, MISSING, Haiku down -> escalate
Held-out tournament 2026-10-16 (111 new questions): 0 wrong; the gated cascade added 8 correct, 0 wrong."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np

from . import facts as F

K = 8
_TOK = re.compile(r"[a-z0-9]+")
_STOP = set("a an the of in on at to for and or is are do does you your have has with what which how be this that "
            "any if by from as can will would please".split())
_TYPE_WORDS = {"money": "money amount salary pay compensation LPA lakhs", "days": "days weeks",
               "phone": "phone mobile number", "date": "date"}   # a unit-only question still finds its card
_YN_Q = re.compile(r"^\s*(are|is|do|does|did|have|has|will|would|can|could|were|was)\b", re.I)
_BARE_LABEL = re.compile(r"^\s*(\+?\d{1,4}|[₹$€£]|\*)?\s*$")    # "+91" beside the box: the label is a value


def _toks(s):
    return {t for t in _TOK.findall(str(s).lower()) if t not in _STOP}


def question_of(label, ref=""):
    """The question a field asks. A label that is only a value shown beside the box ("+91", "₹") names nothing:
    the field's id does ('#phone_number_field_number' -> 'phone number field number')."""
    if not _BARE_LABEL.fullmatch(label or ""):
        return label
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", re.sub(r"^[#.]|\[.*", "", ref or ""))
    return re.sub(r"[_\-.]+", " ", name).strip().lower() or label


def _show(v):
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict) and "text" in v:
        extra = {k: x for k, x in v.items() if k != "text" and x is not None}
        return f"{v['text']} {json.dumps(extra, default=str)}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return str(v)


class Cards:
    """The fact sheet as searchable cards (built once per facts snapshot)."""

    def __init__(self, facts, embed):
        self.facts, self.embed = facts, embed
        self.keys = [k for k in facts if k not in ("today", "place_regions")]
        texts = [f"{k.replace('_', ' ')}: {facts[k]['desc']} {_TYPE_WORDS.get(facts[k]['type'], '')}"
                 for k in self.keys]
        self.toks = [_toks(t) for t in texts]
        self.vecs = np.asarray(embed(texts)) if texts else np.zeros((0, 1))

    def top(self, question, k=K):
        if not self.keys:
            return ["today"]
        q = _toks(question)
        sims = self.vecs @ np.asarray(self.embed([question]))[0]
        lex = np.array([len(q & t) / ((len(q) * len(t)) ** 0.5 or 1) for t in self.toks])
        score = 0.6 * sims + 0.4 * lex          # ponytail: fixed blend, tune if retrieval misses new wordings
        return [self.keys[j] for j in np.argsort(-score)[:k]] + ["today"]


def ask_local(llm, question, kind, options, job, facts, cards):
    """(value, cited card) from the local model, or ('', reason)."""
    lines = "\n".join(f"[{c}] {facts[c]['desc']} ({facts[c]['type']}) = {_show(facts[c]['value'])}" for c in cards)
    opt = f"\nThe answer must be exactly one of: {list(options)}" if options else ""
    prompt = ("You fill one job-application form field for a candidate using ONLY the fact cards below.\n"
              f"Job: {job.get('company') or 'unknown'}, {job.get('location') or 'unknown'}\n"
              f"Field ({kind}): {question}{opt}\n\nFact cards:\n{lines}\n\n"
              "Rules: the value must be copied from one card or derived from it by simple reasoning (age from a date, "
              "comparison, unit conversion, a level implying yes/no, a per-company list for this job's company, a "
              "skill missing from the skills grid = 0). A general fact answers a narrower version of it; a DIFFERENT "
              "quantity (alternate number, percentage vs CGPA, IP agreement vs non-compete) does not. Yes/no questions "
              "answer Yes or No. If the field is not a real question or no card settles it, value is NONE.\n"
              'Reply JSON only: {"value": "...", "card": "card id used"}')
    obj = None
    for _ in range(2):                                    # one retry: a malformed reply is not a NONE
        try:
            reply = F._THINK.sub("", llm(prompt) or "")
            obj, _ = json.JSONDecoder().raw_decode(reply[reply.find("{"):])
            break
        except Exception:
            continue
    if not isinstance(obj, dict):
        return "", "local reply unreadable"
    card = str(obj.get("card") or "").strip()
    m = re.search(r"\[([^\]]+)\]", card)                  # models echo the whole card line
    card = m.group(1) if m else (card.split()[0] if card else "")
    val = obj.get("value")
    val = {True: "Yes", False: "No"}.get(val, val) if isinstance(val, bool) else val
    val = {"true": "Yes", "false": "No"}.get(str(val).strip().lower(), str(val if val is not None else "").strip())
    return val, card


def grounded(value, card, facts):
    """Deterministic: yes/no is a judgment over the card; anything else must appear in (a form of) the card."""
    if value.lower() in ("yes", "no"):
        return True
    v = facts[card]["value"]
    forms = [_show(v), F.render(v) if not isinstance(v, dict) or "text" in v else ""]
    if isinstance(v, date):
        forms += [v.strftime("%d/%m/%Y"), v.strftime("%d-%m-%Y"), str(v.year)]
    if isinstance(v, dict) and "amount" in v and "currency" in v:              # money: any of its units
        inr = v["amount"] * F._TO_INR[v["currency"]] * F._PERIOD[v["period"]]
        forms += [F.render(round(inr / 1e5, 2)), F.render(float(round(inr))), F.render(round(inr / 88 / 12))]
    if isinstance(v, dict) and "text" not in v and re.fullmatch(r"\d+(\.\d+)?", value):
        forms += ["0"] + [F.render(float(x)) for x in v.values() if isinstance(x, (int, float))]
    hay = " ".join(forms).lower()
    nums = re.findall(r"\d+(?:\.\d+)?", value)
    if nums:
        return all(n in hay or n.rstrip("0").rstrip(".") in hay for n in nums)
    return bool(_toks(value)) and _toks(value) <= _toks(hay) | _toks(card)


def _same(a, b) -> bool:
    """The two readers agree on the VALUE, written either way: '25 LPA' = '25' = '2500000' for money,
    '+91 7565052330' = '7565052330' for a phone number."""
    a, b = (str(x).strip().lower() for x in (a, b))
    try:
        return float(a) == float(b)
    except ValueError:
        pass
    if a == b:
        return True
    da, db = (re.sub(r"\D", "", x) for x in (a, b))
    if min(len(da), len(db)) >= 7 and (da.endswith(db) or db.endswith(da)):
        return True                                       # one side carries the dial code
    ma, mb = F.money(a), F.money(b)
    return bool(ma and mb and re.fullmatch(r"[\d.,]+\s*(lpa|lakhs?|l|inr)?", a) and
                re.fullmatch(r"[\d.,]+\s*(lpa|lakhs?|l|inr)?", b) and ma["amount"] == mb["amount"])


def _local(llm, question, kind, options, job, facts, cards):
    """The local reader plus its checks: (value, card) or (None, why)."""
    from .qbank_match import fit_option
    value, card = ask_local(llm, question, kind, options, job, facts, cards)
    if not value or value.upper() == "NONE" or card not in cards:
        return None, f"local none ({card})"
    if options:
        value = fit_option("", value, list(options), None, None)
        if not value:
            return None, "local not an option"
    elif _YN_Q.search(question) and kind not in ("text", "textarea") and value.lower() not in ("yes", "no"):
        return None, "local: yes/no question, other value"
    if kind == "checkbox" and value.lower() not in ("yes", "no"):
        return None, "local: checkbox, other value"
    if not grounded(value, card, facts):
        return None, f"local ungrounded in [{card}]"
    return value, card


def answer(question, kind, options, job, facts, cards, *, local_llm, haiku_llm, cache=None, hint=""):
    """(value or None, note). The note starts with MISSING/DERIVE when Haiku proposes a new fact (the caller saves
    it); 'agree'/'plan only'/'local only' say which reader(s) the value stands on."""
    if F._OPTION_RUN.fullmatch((question or "").strip()):
        return None, "unreadable label"
    with ThreadPoolExecutor(1) as pool:                   # the local reader runs while Haiku compiles
        fut = pool.submit(_local, local_llm, question, kind, options, job, facts, cards.top(question)) \
            if local_llm else None
        try:                                              # Haiku in THIS thread: the plan cache is sqlite
            plan_val, note = F.answer(question, kind, options, job, facts, haiku_llm, cache=cache, hint=hint)
        except Exception as e:
            if fut:
                fut.cancel()
            return None, f"haiku unreachable, escalate: {type(e).__name__}"      # fail closed
        local_val, card = fut.result() if fut else (None, "no local reader")
    if note.startswith(("MISSING", "not a question", "unreadable")):
        return None, note                                 # the schema holds no such fact: don't trust a card
    if plan_val and local_val:
        return (plan_val, f"agree [{card}] | {note}") if _same(plan_val, local_val) else \
            (None, f"disagree local [{card}]={local_val!r} plan={plan_val!r} | {note}")
    if plan_val:
        return plan_val, f"plan only ({card}) | {note}"
    if local_val:                                         # one reader alone is not enough (regression 2026-10-16)
        return None, f"local only [{card}]={local_val!r}, plan had none: escalate (plan: {note[:60]})"
    return None, f"neither: {card}; {note}"


class PlanCache:
    """Compiled plans kept across runs (the `cache=` of answer), keyed by wording + the fact schema, so telling a
    new fact recompiles the wordings that were MISSING it. An unreadable reply ({}) is not kept."""

    def __init__(self, conn, facts):
        import hashlib
        self.conn, self.tag = conn, hashlib.sha1(F.schema(facts).encode()).hexdigest()[:12]
        conn.execute("CREATE TABLE IF NOT EXISTS fact_plan (norm TEXT NOT NULL, schema TEXT NOT NULL, "
                     "out_json TEXT NOT NULL, created_at TEXT, PRIMARY KEY (norm, schema))")

    def get(self, key):
        row = self.conn.execute("SELECT out_json FROM fact_plan WHERE norm=? AND schema=?", (key, self.tag)).fetchone()
        return json.loads(row[0]) if row else None

    def __setitem__(self, key, out):
        if out:
            self.conn.execute("INSERT OR REPLACE INTO fact_plan VALUES (?,?,?,datetime('now'))",
                              (key, self.tag, json.dumps(out)))
            self.conn.commit()
