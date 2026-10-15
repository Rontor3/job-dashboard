"""factcard: retrieval over the FACT SHEET (one card per fact), local model answers from the top cards only.

setup:  one card per facts.build key; embed "key: description" (never the value) with MiniLM.
answer: hybrid retrieve (cosine + token overlap) top-5 (+ today) -> local Ollama reads ONLY those cards and must
        cite one -> deterministic checks (cited card retrieved, option fit, yes/no shape, value grounded in the card)
        -> Haiku plan (facts.answer, schema only, no values) as a cross-check: disagree => escalate. Fallback none."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import numpy as np

K = 8
_TOK = re.compile(r"[a-z0-9]+")
_STOP = set("a an the of in on at to for and or is are do does you your have has with what which how be this that "
            "any if by from as can will would please".split())
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_TYPE_WORDS = {"money": "money amount salary pay compensation LPA lakhs", "days": "days weeks",
               "phone": "phone mobile number", "date": "date"}   # type words help a unit-only question find the card
_YN_Q = re.compile(r"^\s*(are|is|do|does|did|have|has|will|would|can|could|were|was)\b", re.I)


def _toks(s):
    return {t for t in _TOK.findall(str(s).lower()) if t not in _STOP}


def _show(v):
    """A card's value as the local model reads it."""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict) and "text" in v:
        extra = {k: x for k, x in v.items() if k != "text" and x is not None}
        return f"{v['text']} {json.dumps(extra, default=str)}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return str(v)


def setup(env):
    facts = env["facts"]
    keys = [k for k in facts if k != "today"]
    texts = [f"{k.replace('_', ' ')}: {facts[k]['desc']} {_TYPE_WORDS.get(facts[k]['type'], '')}" for k in keys]
    env["fc"] = {"keys": keys, "toks": [_toks(t) for t in texts], "vecs": np.asarray(env["embed"](texts))}


def retrieve(env, question, k=K):
    if env.get("all_cards"):                 # wholebank: no retrieval, the model reads every card
        return list(env["facts"])
    fc = env.get("fc") or (setup(env) or env["fc"])
    q = _toks(question)
    sims = fc["vecs"] @ np.asarray(env["embed"]([question]))[0]
    lex = np.array([len(q & t) / (len(q) ** 0.5 * len(t) ** 0.5 or 1) for t in fc["toks"]])
    score = 0.6 * sims + 0.4 * lex          # ponytail: fixed blend, tune if retrieval misses on new wordings
    return [fc["keys"][j] for j in np.argsort(-score)[:k]] + ["today"]


def ask_local(env, case, cards):
    _, kind, label, options, job, _, _ = case
    facts = env["facts"]
    lines = "\n".join(f"[{c}] {facts[c]['desc']} ({facts[c]['type']}) = {_show(facts[c]['value'])}" for c in cards)
    opt = f"\nThe answer must be exactly one of: {list(options)}" if options else ""
    prompt = ("You fill one job-application form field for a candidate using ONLY the fact cards below.\n"
              f"Job: {job.get('company') or 'unknown'}, {job.get('location') or 'unknown'}\n"
              f"Field ({kind}): {label}{opt}\n\nFact cards:\n{lines}\n\n"
              "Rules: the value must be copied from one card or derived from it by simple reasoning (age from a date, "
              "comparison, unit conversion, a level implying yes/no, a per-company list for this job's company, a "
              "skill missing from the skills grid = 0). A general fact answers a narrower version of it; a DIFFERENT "
              "quantity (alternate number, percentage vs CGPA, IP agreement vs non-compete) does not. Yes/no questions "
              "answer Yes or No. If the field is not a real question or no card settles it, value is NONE.\n"
              'Reply JSON only: {"value": "...", "card": "card id used"}')
    try:
        for attempt in range(2):                       # one retry: a malformed reply is not a NONE
            try:
                reply = _THINK.sub("", env["llm"](prompt) or "")
                obj, _ = json.JSONDecoder().raw_decode(reply[reply.find("{"):])
                break
            except Exception:                          # malformed JSON or a cold-load timeout
                if attempt:
                    raise
        card = str(obj.get("card") or "").strip()
        m = re.search(r"\[([^\]]+)\]", card)             # models often echo the whole card line
        card = m.group(1) if m else card.split()[0] if card else ""
        val = obj.get("value")
        val = {True: "Yes", False: "No"}.get(val, val) if isinstance(val, bool) else val
        val = {"true": "Yes", "false": "No"}.get(str(val).strip().lower(), str(val or "").strip())
        return val, card
    except Exception as e:
        return "", f"LLM-ERROR {type(e).__name__}"


def grounded(value, card, facts):
    """Deterministic: a yes/no is a judgment over the card; anything else must appear in (a form of) the card."""
    from career_agent.memory import facts as F
    if value.lower() in ("yes", "no"):
        return True
    v = facts[card]["value"]
    forms = [_show(v), F.render(v) if not isinstance(v, dict) or "text" in v else ""]
    if isinstance(v, dict) and "amount" in v and "currency" in v:                 # money: any of its units
        inr = v["amount"] * F._TO_INR[v["currency"]] * F._PERIOD[v["period"]]
        forms += [F.render(round(inr / 1e5, 2)), F.render(float(round(inr))), F.render(round(inr / 88 / 12))]
    if card == "skills" and re.fullmatch(r"\d+(\.\d+)?", value):
        forms += ["0"] + [F.render(float(x)) for x in v.values() if x is not None]
    hay = " ".join(forms).lower()
    nums = re.findall(r"\d+(?:\.\d+)?", value)
    if nums:
        return all(n in hay or n.rstrip("0").rstrip(".") in hay for n in nums)
    return bool(_toks(value)) and _toks(value) <= _toks(hay) | _toks(card)


def answer(env, i, case):
    from career_agent.browser.form_model import Field
    from career_agent.memory import facts as F
    from career_agent.memory.qbank_match import fit_option, is_junk
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import answer_methods_bench as bench
    _, kind, label, options, job, _, _ = case
    if is_junk(Field(ref="x", kind=kind, label=label, required=False, options=list(options))) \
            or F._OPTION_RUN.fullmatch(label.strip()):
        env["notes"][i] = "junk"
        return None
    cards = retrieve(env, label)
    value, card = ask_local(env, case, cards)
    if not value or value.upper() == "NONE" or card not in cards:
        env["notes"][i] = f"local none/uncited {card if card.startswith('LLM-ERROR') else ''} top={cards}"
        return None
    if options:
        fitted = fit_option("", value, list(options), None, None)
        if not fitted:
            env["notes"][i] = f"not an option: {value}"
            return None
        value = fitted
    elif _YN_Q.search(label) and kind != "text" and value.lower() not in ("yes", "no"):
        env["notes"][i] = "yes/no question, non yes/no value"
        return None
    if kind == "checkbox" and value.lower() not in ("yes", "no"):
        env["notes"][i] = "checkbox, non yes/no value"
        return None
    if not grounded(value, card, env["facts"]):
        env["notes"][i] = f"ungrounded in [{card}]"
        return None
    if env.get("no_cross_check"):
        env["notes"][i] = f"card={card} solo"
        return value
    try:                                     # Haiku cross-check: question + schema only, never values
        plan_val, note = F.answer(label, kind, options, job, env["facts"], env["haiku"], cache=env["plans"])
    except Exception as e:
        plan_val, note = None, f"haiku error {e}"
    if plan_val in (None, "") and note.startswith(("MISSING", "not a question", "unreadable")):
        env["notes"][i] = f"haiku veto: {note[:80]}"     # the schema says no fact holds this: don't trust a card
        return None
    if plan_val not in (None, "") and not bench.same(value, plan_val):
        env["notes"][i] = f"disagree local={card} haiku plan={note[:120]}"
        return None
    env["notes"][i] = f"card={card} haiku={'agree' if plan_val else note[:40]}"
    return value
