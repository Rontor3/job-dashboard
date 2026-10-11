"""Segmented answers: split a question into the pieces of information it needs, decide for each piece WHERE the
information comes from, write each piece under that source's rule, and join the pieces without a model.

  CANDIDATE   something the applicant did/built/measured      -> passages of their own projects; fact-checked; GAP if absent
  COMPANY     a fact about the employer or role               -> the job description only
  GENERAL     industry-standard knowledge or a hypothetical   -> the practice library; written as 'I would', never as done
  PREFERENCE  what the applicant wants / how they work        -> their own-words stories only; GAP if absent

A pure hypothetical ('how would you...') is one GENERAL piece, never CANDIDATE: the code gates that, not the model.
Same return shape as pipeline.answer_longform, plus `segments` and `chunks` (what was retrieved, for the metrics)."""
from __future__ import annotations

import json
import re

from .kb import Chunk

_EXP = re.compile(
    r"\b(have you|did you|you(?:'ve| have)? (?:personally )?(?:built|shipped|used|led|implemented|designed|worked|run|ran)"
    r"|your (?:experience|work|project)|tell us about a time|describe a (?:time|project)|example (?:of|from) (?:your|a))\b", re.I)
_HYP = re.compile(r"\b(how would you|suppose|imagine|you inherit|what would you|if you (?:were|had))\b", re.I)
_SOURCES = ("CANDIDATE", "COMPANY", "GENERAL", "PREFERENCE")

RULES = {
    "CANDIDATE": "Say only what the PROJECT text states, in first person, naming the project. Copy its facts almost word for "
                 "word and add no detail of your own. If the text does not contain what this part asks for, reply exactly: GAP",
    "GENERAL": "Write the concrete plan or method in first person ('I would...'), specific and in practitioner order. "
               "This is general practice, never claim you did it.",
    "COMPANY": "Use only facts in the JOB DESCRIPTION. If it does not say, reply exactly: GAP",
    "PREFERENCE": "Say only what the material states about the applicant's preferences. If none, reply exactly: GAP",
}
ADJACENT = ("If the PROJECT text has no example of exactly this, use the CLOSEST real example in it (for instance a classical-ML "
            "evaluation when the question names LLMs) and begin the sentence with 'Closest example from my work:'. Only if "
            "nothing in the text is even adjacent, reply exactly: GAP. Copy facts almost word for word; add no detail.")
_MARKER = "Closest example from my work:"


def _clean(raw: str) -> str:
    return re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()


def _json(raw: str) -> dict:
    m = re.search(r"\{.*\}", _clean(raw), flags=re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def _strip_number(q: str) -> str:
    return re.sub(r"^\s*\d+\.\s*|\s*\*\s*$", "", q or "")


def segment(question: str, llm) -> list[dict]:
    """[{part, source}] with at most one piece per source. A hypothetical with no experience cue is one GENERAL piece."""
    if _HYP.search(question) and not _EXP.search(question):
        return [{"part": _strip_number(question), "source": "GENERAL"}]
    prompt = ("Split this job-application question into the separate pieces of information it needs.\n"
              f'QUESTION: "{question}"\n\nFor each piece give a short "part" and a "source":\n'
              "- CANDIDATE: something the applicant personally did, built or measured\n"
              "- COMPANY: a fact about this employer or role\n"
              "- GENERAL: industry-standard knowledge, independent of the applicant's history\n"
              "- PREFERENCE: what the applicant wants or how they work\n"
              'Each "part" must be a short SUB-QUESTION or topic, never an answer and never a claim about the applicant.\n'
              "Use 1-3 pieces. A question asking for BOTH past experience and a method needs a CANDIDATE piece and a GENERAL piece.\n"
              'Reply with ONLY JSON: {"segments": [{"part": "...", "source": "CANDIDATE|COMPANY|GENERAL|PREFERENCE"}]}')
    try:
        raw = llm(prompt)
    except Exception:
        raw = ""
    out: list[dict] = []
    for sg in _json(raw).get("segments", []) if isinstance(_json(raw).get("segments"), list) else []:
        if not isinstance(sg, dict) or sg.get("source") not in _SOURCES or not isinstance(sg.get("part"), str) or not sg["part"].strip():
            continue
        same = next((o for o in out if o["source"] == sg["source"]), None)
        if same:
            same["part"] += " Also: " + sg["part"]
        else:
            out.append({"part": sg["part"].strip(), "source": sg["source"]})
    # an unreadable plan falls back on what the wording says
    return out[:3] or [{"part": _strip_number(question), "source": "CANDIDATE" if _EXP.search(question) else "GENERAL"}]


_KIND_SOURCE = {"own": "CANDIDATE", "company": "COMPANY", "general": "GENERAL"}
_FOLLOW_UP = re.compile(r"^\s*(if|in case|when)\s+(yes|so|no|not|applicable|you answered|you selected)\b", re.I)
_URL = re.compile(r"https?://[^\s)\]>\"']+|\b(?:www\.)?(?:github|gitlab|linkedin|medium|kaggle|huggingface)\.(?:com|co|io)/[^\s)\]>\"']+", re.I)


def sub_asks(question: str, llm) -> list[dict]:
    """One piece per thing the question EXPLICITLY asks for, in order (each backed by a quote of the question's own
    words), tagged with where its information comes from. A hypothetical with no experience cue is all GENERAL.
    Falls back to the coarse split when the model gives nothing usable."""
    from .metrics import explicit_asks
    hypothetical = bool(_HYP.search(question) and not _EXP.search(question))
    asks = explicit_asks(question, llm)
    out = [{"part": a["item"], "source": "GENERAL" if hypothetical else _KIND_SOURCE[a["kind"]], "quote": a["quote"]} for a in asks]
    return out or segment(question, llm)


def invented_links(text: str, chunks, known=()) -> list[str]:
    """Links in `text` that appear in none of the material and are not one of the applicant's known links."""
    seen = (" ".join(c.text for c in chunks) + " " + " ".join(known)).lower().replace("https://", "").replace("http://", "").replace("www.", "")
    bad = []
    for m in _URL.findall(text or ""):
        core = m.lower().rstrip(".,;:").replace("https://", "").replace("http://", "").replace("www.", "")
        if core.rstrip("/") not in seen and core not in bad:
            bad.append(core)
    return bad


def material(seg: dict, question: str, kb, jd_text: str = "", project_id: str | None = None) -> list[Chunk]:
    src, query = seg["source"], f"{seg['part']} {question}"
    if src == "CANDIDATE":
        return kb.passages(query, 5, project_id=project_id)
    if src == "GENERAL":
        return kb.practice_chunks(query, 2)
    if src == "COMPANY":
        return [Chunk("jd", "jd", jd_text.strip()[:1500])] if jd_text.strip() else []
    from .kb import tokens
    want = tokens(query)
    slots = sorted(kb.story_slots(), key=lambda s: -len(want & tokens(kb.get_story(s).text if kb.get_story(s) else "")))
    return [c for c in (kb.get_story(s) for s in slots[:2]) if c]


def _render(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.kind.upper()}{' · ' + c.project_id if c.project_id else ''}]\n{c.text}" for c in chunks)


def _write(seg: dict, chunks: list[Chunk], question: str, llm, *, adjacent: bool = False, limit=None) -> str:
    rule = ADJACENT if adjacent and seg["source"] == "CANDIDATE" else RULES[seg["source"]]
    size = ("Write 5-8 sentences covering EVERY thing the question asks for (its sub-asks), in order. "
            if seg["source"] == "GENERAL" and len(seg["part"]) > 120 else "Write 2-5 sentences. ")
    if limit:
        size += f"Keep it under {limit} characters. "
    material_text = _render(chunks) or "(no written material: use well-established general practice)"
    prompt = (f"QUESTION (for context): {question}\nWRITE ONLY THIS PART: {seg['part']}\nSOURCE TYPE: {seg['source']}\n"
              f"RULE: {rule}\n{size}Do not restate the question. No headings.\n\nMATERIAL:\n{material_text}\n\nPart:")
    try:
        return _clean(llm(prompt))
    except Exception:
        return "GAP"


def supported(text: str, chunks: list[Chunk], llm) -> bool:
    """Strict second pass: does the material state every fact about the applicant that TEXT claims?"""
    prompt = ("You are a strict fact checker. Below is MATERIAL and a TEXT written from it.\n"
              "Reply NO if the TEXT states anything about what the applicant did, used, measured or achieved that is not "
              "written in the MATERIAL (an invented test set, method or number, or an unrelated project passed off as relevant). "
              f"Otherwise reply YES. One word, then a short reason.\n\nMATERIAL:\n{_render(chunks)}\n\nTEXT:\n{text}\n\nVerdict:")
    try:
        return _clean(llm(prompt)).upper().startswith("YES")
    except Exception:
        return False


def _is_gap(text: str) -> bool:
    return not text.strip() or text.strip().upper().startswith("GAP")


def _dedupe(text: str, seen: list) -> str:
    """Drop a sentence that repeats an earlier one in `seen` (word-set Jaccard >= 0.6), updating `seen`."""
    kept = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        words = set(re.findall(r"[a-z0-9]+", sent.lower()))
        if len(words) >= 4 and any(len(words & w) / len(words | w) >= 0.6 for w in seen):
            continue
        kept.append(sent)
        seen.append(words)
    return " ".join(kept)


def join(parts: list[tuple[dict, str]]) -> str:
    """No model: the pieces in the order the question asked for them; the closest-example marker is printed once."""
    seen: list = []          # repeats are only removed between PERSONAL pieces (they restate one passage); general points stay
    text = " ".join(_dedupe(t.strip(), seen) if sg["source"] == "CANDIDATE" else t.strip() for sg, t in parts).strip()
    first = text.find(_MARKER)
    return text if first < 0 else text[: first + len(_MARKER)] + text[first + len(_MARKER):].replace(_MARKER, "")


def _piece(sg, chunks, question, llm, known, limit, repair_for: str | None = None) -> str:
    """Write one piece; a CANDIDATE piece is fact-checked, link-checked, and retried once in 'closest example' mode."""
    def ok(text):
        return not _is_gap(text) and not invented_links(text, chunks, known) and (sg["source"] != "CANDIDATE" or supported(text, chunks, llm))
    text = _write(sg, chunks, question, llm, limit=limit) if not repair_for else _write(
        {**sg, "part": sg["part"] + f"  (A previous draft did not answer this. Answer exactly this, in 1-3 sentences.)"}, chunks, question, llm, limit=limit)
    if sg["source"] != "CANDIDATE":
        return text if ok(text) else "GAP"
    if _is_gap(text):
        text = _write(sg, chunks, question, llm, adjacent=True, limit=limit)
    if ok(text):
        return text
    retry = _write(sg, chunks, question, llm, adjacent=True, limit=limit)
    return retry if ok(retry) else "GAP"


def answer_segmented(question, *, job, kb, llm, limit=None, by_asks: bool = True, repair: bool = True) -> dict:
    """by_asks=True writes one piece per explicit sub-ask (so every point asked gets its own piece); False is the coarse
    1-3 piece split. `repair` re-writes any piece the coverage check finds does not answer its ask."""
    jd = (job.get("description") if isinstance(job, dict) else "") or ""
    if _FOLLOW_UP.match(_strip_number(question)):                 # "If yes, what is it?": the parent question is missing
        return {"answer": None, "flags": ["follow_up_without_parent"], "unsupported_company_claims": [], "confidence": None,
                "basis": "a follow-up question whose parent question was not read", "prompt": "", "needs": [], "project_id": None,
                "used": [], "plan_source": "segments", "plan_reason": "follow-up", "segments": [], "chunks": []}
    known = [str(v) for v in (getattr(kb, "_facts", {}) or {}).values() if isinstance(v, str)]
    segs = sub_asks(question, llm) if by_asks else segment(question, llm)
    pieces, chunks_all = [], []
    main = kb.main_project(question) if any(sg["source"] == "CANDIDATE" for sg in segs) else None   # one project per answer
    for sg in segs:
        chunks = material(sg, question, kb, jd, project_id=main)
        text = _piece(sg, chunks, question, llm, known, limit)
        pieces.append({"seg": sg, "chunks": chunks, "text": text})
        chunks_all += [c for c in chunks if c.id not in {x.id for x in chunks_all}]
    if repair:                                                     # every written piece must actually answer its ask
        from .metrics import judge_addressed
        live = [p for p in pieces if not _is_gap(p["text"])]
        flags = judge_addressed(question, join([(p["seg"], p["text"]) for p in live]), [p["seg"]["part"] for p in live], llm) if live else None
        for p, ok in zip(live, flags or []):
            if not ok:
                retry = _piece(p["seg"], p["chunks"], question, llm, known, limit, repair_for=p["seg"]["part"])
                if not _is_gap(retry):
                    p["text"] = retry
    parts = [(p["seg"], p["text"]) for p in pieces if not _is_gap(p["text"])]
    rows = [{"source": p["seg"]["source"], "part": p["seg"]["part"], "chunks": [c.id for c in p["chunks"]], "gap": _is_gap(p["text"])} for p in pieces]
    flags = ["gap:" + r["part"][:60] for r in rows if r["gap"]]
    answer = join(parts)
    if limit and len(answer) > limit:
        from .verify import fit_length
        answer, _ = fit_length(answer, limit)
    held = any(r["gap"] and r["source"] in ("CANDIDATE", "PREFERENCE") for r in rows)     # a missing own-experience piece: human decides
    return {"answer": answer or None, "flags": flags, "unsupported_company_claims": [],
            "confidence": None if (held or not answer) else 85, "basis": "segmented; per-source rules",
            "prompt": "", "needs": [r["source"] for r in rows], "project_id": None,
            "used": [c.id for c in chunks_all], "plan_source": "segments", "plan_reason": "; ".join(f"{r['source']}: {r['part'][:50]}" for r in rows),
            "segments": rows, "chunks": chunks_all}
