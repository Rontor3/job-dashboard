"""A note to a team ('Start a conversation with the team at X', 'Reach out to the founders'): written like a person who
looked the company up and talks to the founders: what you like about their idea, why this team, a line on what you have done,
what you want to do next (user feedback 2026-10-22). Never the stock opening of an ingredient note, never the job
post's own sentences."""
from __future__ import annotations

import re

from .kb import Chunk

OUTREACH = re.compile(r"\b(start a conversation|reach out to|message (to|for) the|note to the|introduce yourself|"
                      r"say hello|cover (letter|note))\b", re.I)
_STOCK_OPEN = re.compile(r"^\s*(i enjoy|i am excited|i'm excited|i am writing|i'm writing|i came across|i hope)\b", re.I)
_GREETING = re.compile(r"^\s*(hi|hello|hey)\b[^,\n]{0,40},\s*", re.I)
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


def _goals(corpus) -> list[Chunk]:
    """The applicant's own words on what they want to do next (a story slot), for the note's closing line."""
    try:
        return corpus.search("what I am looking for next, the work I want to do, career goals", 1, kinds={"story"}, floor=0.0)
    except Exception:
        return []


def _prompt(question, company, facts, work, limit, avoid=None, goals=(), post="") -> str:
    size = f"under {limit} characters" if limit else "100-150 words"
    fix = f"\nYour last draft copied this phrase; say it in your own words instead: \"{avoid}\"\n" if avoid else ""
    return (f"Write the applicant's opening message to the team at {company}, in the first person, answering:\n\"{question}\"\n\n"
            "This starts a CONVERSATION with the founders, not a cover letter: talk to them (\"you\", \"your team\"), warm, "
            f"plain, natural words with contractions; {size}; short paragraphs. Open with \"Hi {company} team,\" and no sign-off.\n"
            "Cover these four beats, in this order:\n"
            f"1. What you like about their idea: ONE specific thing from COMPANY FACTS (what they build, the problem they "
            "solve, a launch), in your own words, and why it clicks for you.\n"
            "2. Why you want to be part of this team: what about joining them, at this stage, appeals to you.\n"
            "3. Briefly what you have done: one or two projects from YOUR WORK that connect to what they build, one short "
            "sentence each (name it, what you built). No deep explanations, no résumé tone.\n"
            "4. What you want to do going ahead: one sentence, from YOUR GOALS if given, tied to what you could build with them.\n"
            "- Use only facts in the material; no invented numbers, names or links. Never guess what the company does or "
            "its industry: with no COMPANY FACTS, talk about the work in the JOB POST instead.\n"
            "- Put each beat in its own short paragraph, separated by a blank line.\n"
            "- Do not open the body with 'I enjoy', 'I am excited', 'I am writing' or 'I came across'. Do not copy sentences "
            "from the material; rephrase them.\n" + fix +
            "\nCOMPANY FACTS:\n" + ("\n".join(f"- {f}" for f in facts) or f"- (no research found; only the job post below)") +
            ("\n\nJOB POST:\n" + post if post and not facts else "") + "\n\nYOUR WORK:\n" + "\n".join(f"- {c.text}" for c in work) +
            ("\n\nYOUR GOALS (your own words):\n" + "\n".join(f"- {c.text}" for c in goals) if goals else "") + "\n\nMessage:")


def answer_outreach(question, *, job, corpus, research, llm, limit=None) -> dict:
    from .asks import _PREAMBLE, _THINK, _dedupe_sentences
    company = job.get("company") or "the company"
    facts = [f.text for f in (getattr(research, "facts", None) or [])][:5]
    work, goals = _projects(corpus, job), _goals(corpus)
    sources = [c.text for c in corpus.items if c.kind in ("passage", "story", "company")]
    text, avoid, notes = None, None, []
    for _ in range(2):                                       # one rewrite when it copies or opens with a stock line
        raw = llm(_prompt(question, company, facts, work, limit, avoid, goals, (job.get("description") or "")[:1200]))
        text = _dedupe_sentences(_PREAMBLE.sub("", _THINK.sub("", raw or "")).strip())
        avoid = copied_run(text, sources) or (text.split(".")[0] if _STOCK_OPEN.match(_GREETING.sub("", text)) else None)
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
