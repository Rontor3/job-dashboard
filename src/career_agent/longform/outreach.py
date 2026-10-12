"""A note to a team ('Start a conversation with the team at X', 'Reach out to the founders'): written like a person who
looked the company up — one specific thing about what they build, one or two of your projects that connect to it in a
sentence each, what you are looking for when asked. Never the stock opening of an ingredient note, never the job
post's own sentences."""
from __future__ import annotations

import re

from .kb import Chunk

OUTREACH = re.compile(r"\b(start a conversation|reach out to|message (to|for) the|note to the|introduce yourself|"
                      r"say hello|cover (letter|note))\b", re.I)
_STOCK_OPEN = re.compile(r"^\s*(i enjoy|i am excited|i'm excited|i am writing|i'm writing|i came across|i hope)\b", re.I)
_WORD = re.compile(r"[a-z0-9']+")


def copied_run(text: str, sources: list[str], n: int = 8) -> str | None:
    """The first run of `n` words `text` shares verbatim with any source, else None."""
    words = _WORD.findall((text or "").lower())
    grams = set()
    for s in sources:
        w = _WORD.findall((s or "").lower())
        grams.update(" ".join(w[i:i + n]) for i in range(len(w) - n + 1))
    return next((" ".join(words[i:i + n]) for i in range(len(words) - n + 1) if " ".join(words[i:i + n]) in grams), None)


def _projects(corpus, job: dict, k: int = 2) -> list[Chunk]:
    query = f"{job.get('title', '')} {(job.get('description') or '')[:600]}"
    ranked = corpus.search(query, 12, kinds={"passage"}, per_unit=1, floor=0.0)
    out, seen = [], set()
    for c in ranked:
        if c.project_id and c.project_id not in seen:
            seen.add(c.project_id)
            out += [c] + ([corpus.kb.card(c.project_id)] if corpus.kb.card(c.project_id) else [])
        if len(seen) >= k:
            break
    return out


def _prompt(question, company, facts, work, limit, avoid=None) -> str:
    size = f"under {limit} characters" if limit else "90-140 words"
    fix = f"\nYour last draft copied this phrase; say it in your own words instead: \"{avoid}\"\n" if avoid else ""
    return (f"Write the applicant's note to the team at {company}, in the first person, answering:\n\"{question}\"\n\n"
            f"Sound like a real person who has looked into {company}: warm, specific, plain words; {size}; two short "
            "paragraphs; no greeting or sign-off unless the question asks for one.\n"
            f"- Open with what draws you to {company}, built on ONE specific item from COMPANY FACTS (what they build, a "
            "launch, a customer, the problem they solve), in your own words.\n"
            "- Then one or two of your projects from YOUR WORK that connect to what they build: name it and say in one "
            "sentence what you built and why it is relevant. Do not explain projects in depth.\n"
            "- If the question asks what you are looking for, say it in one sentence.\n"
            "- Use only facts in the material; no invented numbers, names or links.\n"
            "- Do not open with 'I enjoy', 'I am excited', 'I am writing' or 'I came across'. Do not copy sentences from "
            "the material; rephrase them.\n" + fix +
            f"\nCOMPANY FACTS:\n" + ("\n".join(f"- {f}" for f in facts) or f"- (only the job post: {company} is hiring)") +
            "\n\nYOUR WORK:\n" + "\n".join(f"- {c.text}" for c in work) + "\n\nNote:")


def answer_outreach(question, *, job, corpus, research, llm, limit=None) -> dict:
    from .asks import _PREAMBLE, _THINK, _dedupe_sentences
    company = job.get("company") or "the company"
    facts = [f.text for f in (getattr(research, "facts", None) or [])][:5]
    work = _projects(corpus, job)
    sources = [c.text for c in corpus.items if c.kind in ("passage", "story", "company")]
    text, avoid, notes = None, None, []
    for _ in range(2):                                       # one rewrite when it copies or opens with a stock line
        raw = llm(_prompt(question, company, facts, work, limit, avoid))
        text = _dedupe_sentences(_PREAMBLE.sub("", _THINK.sub("", raw or "")).strip())
        avoid = copied_run(text, sources) or (text.split(".")[0] if _STOCK_OPEN.match(text) else None)
        if not avoid:
            break
        notes.append("rewrote_copied_phrase")
    if limit and text:
        from .verify import fit_length
        text, _ = fit_length(text, limit)
    chunks = work + [Chunk(f"research:{i}", "company", f) for i, f in enumerate(facts)]
    return {"answer": text or None, "chunks": chunks, "flags": [], "notes": notes, "confidence": 85 if text else None,
            "basis": f"note to {company}: {len(facts)} researched facts + {len({c.project_id for c in work})} projects",
            "used": [c.id for c in chunks], "asks": [question], "unsupported_company_claims": []}
