"""Answer a technical-knowledge question ("explain attention", "bagging vs boosting", "what is the bias-variance tradeoff").

These need NO records of the applicant: the answer comes from the model's own knowledge, written the way a strong candidate
would answer in an interview. The applicant's own work appears only when retrieval found a passage that genuinely relates, as
ONE closing sentence limited to what that passage states. Nothing about the applicant is ever claimed otherwise.

The result says where the content came from (`source`: "general knowledge" or "general knowledge + your project") so a human can
see which answers rest on the model's memory, which no file of the applicant's can verify."""
from __future__ import annotations

import re
import time

import json

from .kb import Chunk, _STOP, _WORD, _stem

STYLE = ("Answer like a strong data science candidate in an interview: start with the direct answer, then the key mechanism or "
         "distinction, then when to use it or what to watch for. 90 to 150 words, plain prose, no headings, no bullet points. "
         "Be precise; if you are not sure of a detail, leave it out rather than guess. Do not restate the question.")


def _clean(raw: str) -> str:
    return re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()


def write_technical(question: str, evidence: list[Chunk], llm, limit: int | None = None) -> dict:
    link = ""
    if evidence:
        link = ("\n\nTHE APPLICANT'S OWN WORK (the only personal facts you may use):\n" + "\n".join(c.text[:600] for c in evidence[:1])
                + "\n\nAfter the explanation add ONE closing sentence beginning 'In my work, ' that uses only facts stated above. "
                  "Do not claim anything about the applicant that is not stated above.")
    else:
        link = "\n\nMake NO claims about the applicant's own experience, projects or past work."
    size = f" Keep it under {limit} characters." if limit else ""
    prompt = f"You are answering a technical interview question.\n{STYLE}{size}\n\nQUESTION: {question}{link}\n\nAnswer:"
    t = time.time()
    try:
        text = _clean(llm(prompt))
    except Exception:
        text = ""
    return {"answer": text or None, "source": "general knowledge + your project" if evidence else "general knowledge",
            "seconds": round(time.time() - t, 1), "words": len(text.split()), "prompt": prompt}


# --- the link to the applicant's own work: only when it is about the SAME technique -------------------------------------

_GENERIC = {"explain", "difference", "between", "would", "should", "could", "does", "work", "works", "first", "pick", "each", "what",
            "when", "which", "model", "models", "data", "dataset", "handle", "use", "used", "using", "tune", "tuning", "good", "best"}


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall((text or "").lower()) if len(w) >= 4 and w not in _STOP and w not in _GENERIC}


def link_evidence(question: str, corpus, llm, candidates: int = 4) -> list[Chunk]:
    """The one passage of the applicant's work to cite, or [] . Three gates, all required:
       1. raw embedding similarity >= 0.25 (corpus.close);
       2. it shares a SPECIFIC term with the question: a content word that appears in at most a quarter of all passages
          ("imbalance", "attention"), so 'model' or 'class' scattered everywhere cannot link;
       3. a model yes/no: does the passage describe the applicant's own work on the SAME technique or problem the question
          asks about, not merely the same broad field?"""
    pool = [c for c in corpus.items if c.kind == "passage"]
    df: dict[str, int] = {}
    for c in pool:
        for t in _terms(c.text):
            df[t] = df.get(t, 0) + 1
    rare = lambda t: df.get(t, 0) <= max(1, len(pool) // 4)
    q_terms = _terms(question)
    for c in corpus.close(question, candidates, kinds={"passage"}, min_cos=0.25, per_unit=1):
        shared = {t for t in q_terms & _terms(c.text) if rare(t)}
        if not shared:
            continue
        prompt = ("Does the PASSAGE describe the applicant's own work on the SAME specific technique or problem that the QUESTION asks "
                  "about (not merely the same broad field)? Answer YES or NO, then a short reason.\n\n"
                  f"QUESTION: {question}\n\nPASSAGE:\n{c.text[:700]}\n\nAnswer:")
        try:
            if _clean(llm(prompt)).upper().startswith("YES"):
                return [c]
        except Exception:
            return []
    return []


# --- fact-check ----------------------------------------------------------------------------------------------------------

def _json(raw: str) -> dict:
    m = re.search(r"\{.*\}", _clean(raw), flags=re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def verify(question: str, answer: str, llm) -> dict:
    """Strict reviewer: list the answer's factual claims and mark each correct / incorrect / uncertain. {"ok", "wrong": [...], "uncertain": [...]}.
    `ok` is False if any claim is incorrect; an unreadable reply is NOT ok (never assumed fine). The reviewer is only as good as the
    model behind it: see scripts/technical_verifier_check.py for how well the local model catches planted errors."""
    prompt = ("You are a strict technical reviewer. Read the ANSWER to the interview QUESTION. List every factual claim it makes and "
              "judge each one against established knowledge: correct, incorrect, or uncertain. Be careful with swapped definitions, "
              "reversed cause and effect, and claims that something 'always' or 'never' happens.\n"
              f"QUESTION: {question}\n\nANSWER:\n{answer}\n\n"
              'Reply with ONLY JSON: {"claims": [{"claim": "...", "verdict": "correct|incorrect|uncertain", "correction": "the true statement if incorrect"}]}')
    try:
        claims = _json(llm(prompt)).get("claims")
    except Exception:
        claims = None
    if not isinstance(claims, list) or not claims:
        return {"ok": False, "wrong": [], "uncertain": [], "unreadable": True}
    wrong = [c for c in claims if isinstance(c, dict) and str(c.get("verdict", "")).lower() == "incorrect"]
    unsure = [c for c in claims if isinstance(c, dict) and str(c.get("verdict", "")).lower() == "uncertain"]
    return {"ok": not wrong, "wrong": wrong, "uncertain": unsure, "unreadable": False}


def personal_sentence_ok(answer: str, evidence: list[Chunk]) -> bool:
    """The closing 'In my work, ...' sentence must use only words that the evidence passage contains."""
    m = re.search(r"In my work,\s*(.+)$", answer.strip(), flags=re.S)
    if not m:
        return True
    ev = _terms(" ".join(c.text for c in evidence))
    said = _terms(m.group(1))
    return bool(said) and len(said - ev) / len(said) <= 0.35


def answer_technical(question: str, corpus, writer, checker, limit: int | None = None) -> dict:
    """Write a technical answer, then fact-check it. If the reviewer finds an incorrect claim, rewrite once with the corrections as
    constraints and check again. Status: 'checked' (no claim flagged or doubted), 'unsure' (nothing incorrect, but the reviewer doubts
    some claims: they are listed and a human should read them), 'corrected' (rewritten once after a flagged claim), 'corrected, unsure',
    or 'needs review' (still flagged, or the reviewer could not judge)."""
    evidence = link_evidence(question, corpus, checker)
    out = write_technical(question, evidence, writer, limit)
    if out["answer"] and evidence and not personal_sentence_ok(out["answer"], evidence):
        out = write_technical(question, [], writer, limit)               # the personal sentence strayed from the passage: drop the link
        evidence = []
    check = verify(question, out["answer"] or "", checker) if out["answer"] else {"ok": False, "wrong": [], "uncertain": [], "unreadable": True}
    status, rewrites = ("checked" if check["ok"] and not check["uncertain"] else "unsure" if check["ok"] else "needs review"), 0
    if out["answer"] and check["wrong"]:
        fixes = "\n".join(f"- {c.get('claim')}: {c.get('correction')}" for c in check["wrong"])
        retry_q = f"{question}\n\nA reviewer found these errors in an earlier draft, so do not repeat them:\n{fixes}"
        retry = write_technical(retry_q, evidence, writer, limit)
        rewrites = 1
        if retry["answer"]:
            again = verify(question, retry["answer"], checker)
            if again["ok"]:
                out, check = retry, again
                status = "corrected" if not again["uncertain"] else "corrected, unsure"
    return {**out, "status": status, "evidence": [c.id for c in evidence], "wrong_claims": [c.get("claim") for c in check["wrong"]],
            "uncertain_claims": [c.get("claim") for c in check["uncertain"]], "rewrites": rewrites}
