"""Retrieval and answer metrics for long-form answers, judged by a model (local by default), each 0..1.

  contextual_relevancy  share of the retrieved passages that bear on the question          (the one we maximise)
  contextual_precision  are the relevant passages ranked near the top? (average precision over the ranking)
  contextual_recall     share of the information the question needs FROM THE APPLICANT'S DATA that the passages contain
  answer_relevancy      share of what the question asks that the answer actually addresses
  faithfulness          share of the answer's claims about the applicant that the passages support  (guard, not a goal)

Not every question needs retrieval: a 'how would you...' question is answered from general practice. So the judge first
splits what the question needs into items tagged own / company / general; `needs_retrieval` is true when any item is own
or company, and the contextual metrics are only meaningful (and only averaged) for those questions. Recall counts only the
own/company items, because general items are not supposed to come from the applicant's data.

All judge calls are batched (one call lists every passage or item), so one question costs about five calls."""
from __future__ import annotations

import json
import re

_MAX_CHUNK = 1500         # was 600: passages run to 700 chars, so facts at a passage's end were judged 'unsupported'


def _clean(raw) -> str:
    return re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()


def _json(raw):
    text = _clean(raw)
    m = re.search(r"[\[{].*[\]}]", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _ask(judge, prompt, retries: int = 1):
    for _ in range(retries + 1):
        try:
            data = _json(judge(prompt))
        except Exception:
            data = None
        if data is not None:
            return data
    return None


def _numbered(chunks) -> str:
    return "\n".join(f"[{i + 1}] {(c.text if hasattr(c, 'text') else str(c))[:_MAX_CHUNK]}" for i, c in enumerate(chunks))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def explicit_asks(question: str, judge) -> list[dict]:
    """The separate things the question EXPLICITLY asks for, as [{item, kind, quote}] with kind own | company | general.
    Each item must carry a quote of the question's own words, and every word of the quote must occur in the question:
    an item the model made up ("integrate with a CRM") has no such quote and is dropped."""
    prompt = ("List each separate thing this job-application question explicitly asks the applicant to provide, in the order asked. "
              "Do NOT add what a good answer might contain; only what the question itself asks for.\n"
              f'QUESTION: "{question}"\n\nFor each ask give:\n'
              '- "item": a short phrase\n- "quote": the exact words from the question that ask for it\n'
              '- "kind": own (needs the applicant\'s own experience, projects or numbers) | company (facts about the employer or role) | '
              'general (industry-standard knowledge or a reasoned plan)\n'
              'Reply with ONLY JSON: {"items": [{"item": "...", "quote": "...", "kind": "own|company|general"}]} (1 to 6 items).')
    data = _ask(judge, prompt)
    items = data.get("items") if isinstance(data, dict) else None
    qwords = _words(question)
    out = []
    for i in items if isinstance(items, list) else []:
        if not isinstance(i, dict) or i.get("kind") not in ("own", "company", "general") or not i.get("item"):
            continue
        quote = _words(str(i.get("quote") or ""))
        if len(quote) >= 2 and quote <= qwords:                       # the quote really is from the question
            out.append({"item": str(i["item"])[:120], "kind": i["kind"], "quote": str(i["quote"])[:160]})
    return out[:6]


required_items = explicit_asks            # older name, kept for the scripts and tests that import it


def _flags(data, key: str, n: int) -> list[bool] | None:
    """Verdicts from {"judgments": [{"n": 1, "why": "...", "<key>": true}, ...]}; exactly one per item or None."""
    rows = data.get("judgments") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    got = {}
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("n"), int) and 1 <= r["n"] <= n:
            got[r["n"]] = bool(r.get(key))
    return [got[i] for i in range(1, n + 1)] if len(got) == n else None


def judge_relevance(question: str, chunks, judge) -> list[bool] | None:
    """One flag per passage: does it contain information that helps answer ANY part of the question?"""
    if not chunks:
        return []
    prompt = ("You are checking retrieved PASSAGES for a job-application QUESTION. For each numbered passage decide if it contains "
              "information that helps answer ANY part of the question, even partly (a fact, example, method, outcome or "
              "background the answer could use). It is NOT relevant only if it is about something unrelated to what is asked.\n"
              f'QUESTION: "{question}"\n\nPASSAGES:\n{_numbered(chunks)}\n\n'
              'Reply with ONLY JSON: {"judgments": [{"n": 1, "why": "under 12 words", "relevant": true}, ...]} with one entry per passage.')
    return _flags(_ask(judge, prompt), "relevant", len(chunks))


def average_precision(flags: list[bool]) -> float | None:
    """Rank-aware precision: mean of precision@k over the positions of the relevant passages."""
    if not flags:
        return None
    hits, total = 0, 0.0
    for k, rel in enumerate(flags, 1):
        if rel:
            hits += 1
            total += hits / k
    return round(total / hits, 4) if hits else 0.0


def judge_support(items: list[str], chunks, judge, label: str = "ITEM") -> list[bool] | None:
    """One flag per item: do the passages contain the information for it?"""
    if not items or not chunks:
        return [False] * len(items) if items else []
    listed = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(items))
    prompt = (f"For each numbered {label}, decide whether the PASSAGES contain the information needed for it. Supported means the "
              "passages state something that actually answers it (a related fact or example counts if it genuinely answers); "
              "not supported means the passages say nothing about it.\n\n"
              f"{label}S:\n{listed}\n\nPASSAGES:\n{_numbered(chunks)}\n\n"
              'Reply with ONLY JSON: {"judgments": [{"n": 1, "why": "under 12 words", "supported": true}, ...]} with one entry per item.')
    return _flags(_ask(judge, prompt), "supported", len(items))


def judge_addressed(question: str, answer: str, items: list[str], judge) -> list[bool] | None:
    """One flag per item: does the ANSWER address it?"""
    if not items:
        return []
    listed = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(items))
    prompt = ("For each numbered ITEM the question needs, decide whether the ANSWER addresses it directly.\n"
              f'QUESTION: "{question}"\n\nITEMS:\n{listed}\n\nANSWER:\n{answer}\n\n'
              'Reply with ONLY JSON: {"judgments": [{"n": 1, "why": "under 12 words", "addressed": true}, ...]} with one entry per item.')
    return _flags(_ask(judge, prompt), "addressed", len(items))


def judge_faithfulness(answer: str, chunks, judge) -> float | None:
    """Share of the answer's factual claims about the applicant that the passages state. 1.0 when it makes none."""
    prompt = ("List each factual claim in the ANSWER about what the applicant did, built, used, measured or achieved, and say "
              "whether the PASSAGES state it. General statements of method ('I would...') are not claims.\n\n"
              f"PASSAGES:\n{_numbered(chunks)}\n\nANSWER:\n{answer}\n\n"
              'Reply with ONLY JSON: {"claims": [{"claim": "...", "stated": true}]} (empty list if no claims).')
    data = _ask(judge, prompt)
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, list):
        return None
    if not claims:
        return 1.0
    return round(sum(1 for c in claims if isinstance(c, dict) and c.get("stated")) / len(claims), 4)


def _share(flags) -> float | None:
    return None if not flags else round(sum(flags) / len(flags), 4)


def score_retrieval(question: str, chunks, judge, items=None) -> dict:
    """Contextual relevancy / precision / recall for one retrieval (a ranked list of Chunk)."""
    items = items if items is not None else required_items(question, judge)
    flags = judge_relevance(question, chunks, judge)
    retrieval_items = [i["item"] for i in items if i["kind"] in ("own", "company")]
    support = judge_support(retrieval_items, chunks, judge) if retrieval_items else None
    return {"needs_retrieval": bool(retrieval_items), "items": items,
            "contextual_relevancy": _share(flags), "contextual_precision": average_precision(flags) if flags is not None else None,
            "contextual_recall": _share(support) if retrieval_items else None,
            "relevant": flags, "supported": support, "n_chunks": len(chunks)}


def score_answer(question: str, answer: str, chunks, judge, items=None) -> dict:
    """Answer relevancy and faithfulness for one written answer, given the passages it was written from."""
    items = items if items is not None else required_items(question, judge)
    addressed = judge_addressed(question, answer, [i["item"] for i in items], judge)
    return {"answer_relevancy": _share(addressed), "addressed": addressed,
            "faithfulness": judge_faithfulness(answer, chunks, judge) if answer else None}
