"""Long answers ask by ask: split the question into what it explicitly asks, fetch material FOR EACH ask across all the
applicant's work, then write one answer that takes the asks in order (logic iterated with scripts/longform_iterate.py).

Why: the earlier pipelines answer from one project's passages, so an ask whose evidence lives in another project, in a
project's results card, or in the profile's links goes unanswered or gets invented. Here every ask brings its own material:
  own      passages across projects, + the result cards of those projects when the ask is about outcomes
  links    the applicant's profile links (never a made-up URL)
  general  the practice notes, else well-established practice
  company  the job posting
  preference  the applicant's own-words stories"""
from __future__ import annotations

import re

from .kb import Chunk

_OUTCOME = re.compile(r"\b(result|outcome|impact|happen\w*|after launch|measur\w*|metric|success|improv\w*|achiev\w*)\b", re.I)
_LINK = re.compile(r"\b(link|url|github|repo\w*|demo|portfolio|website|write-?up|article|paper)\b", re.I)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_PREAMBLE = re.compile(r"^\s*(closest example from my work|here is|here's|sure)[^:\n]{0,40}:\s*", re.I)
_LINK_KEYS = ("github_url", "linkedin_url", "portfolio_url")
_STACK = re.compile(r"\b(model|tool\w*|stack|tech\w*|framework|librar\w*|language)\b", re.I)
_ONE_THING = re.compile(r"\b(describe|share|tell us about|give)\s+(a|an|one|the)\b|\bthe most\b|\bone example\b|\ban? (ai|llm|ml)?\s*"
                        r"(product|system|agent|project|workflow|application)\b", re.I)


def _links(kb) -> list[Chunk]:
    facts = getattr(kb, "_facts", {}) or {}
    what = {"github_url": "GitHub profile, where the applicant's code and projects are", "linkedin_url": "LinkedIn profile",
            "portfolio_url": "portfolio site"}
    text = "; ".join(f"{what[k]}: {facts[k]}" for k in _LINK_KEYS if str(facts.get(k) or "").strip())   # it9: say what each is
    return [Chunk("fact:links", "fact", f"The applicant's own links — {text}")] if text else []


def project_for(asks: list[dict], question: str, corpus) -> str | None:
    """it6: when the question wants ONE thing, the single project that best covers ALL its own-experience asks (sum over
    asks of that project's best passage score) — not each ask's nearest project, which split 1012 across two."""
    import numpy as np
    own = [a for a in asks if a["source"] == "CANDIDATE"] or asks
    total: dict = {}
    for a in own:
        s = corpus.scores(f"{a['part']} {question}")
        best: dict = {}
        for i, c in enumerate(corpus.items):
            if c.kind == "passage" and c.project_id and s[i] > best.get(c.project_id, -1.0):
                best[c.project_id] = float(s[i])
        for pid, v in best.items():
            total[pid] = total.get(pid, 0.0) + v
    return max(total, key=total.get) if total else None


def material_for(ask: dict, question: str, kb, corpus, project_id: str | None = None, allowed=None,
                 research=None) -> list[Chunk]:
    query = f"{ask['part']} {question}"
    src = ask["source"]
    if src == "GENERAL":
        return corpus.close(query, 2, kinds={"practice"})
    if src == "COMPANY":
        # what the company builds and is known for (longform/research.py) leads; one piece of the posting for the role
        facts = [Chunk(f"research:{i}", "company", f"{f.text} (source: {f.source_url})")
                 for i, f in enumerate((getattr(research, "facts", None) or [])[:5])]
        return facts + corpus.search(query, 1 if facts else 2, kinds={"company"}, floor=0.0)
    if src == "PREFERENCE":
        return corpus.search(query, 2, kinds={"story"}, floor=0.05)
    # it2: the ask on its own AND in context, fused (the whole question alone dilutes a narrow ask like "primary model")
    if project_id:                                       # the question wants ONE thing: that project's passages only
        ranked = corpus.search_multi([ask["part"], query], 12, kinds={"passage"}, per_unit=12, floor=0.0)
        out = [c for c in ranked if c.project_id == project_id][:4]
        # it7 borrowed another project's best passage when the chosen one had nothing near the top for an ask: fixed 922
        # but cost answer relevancy elsewhere (0.95 -> 0.90 averaged over two judgings) -> reverted
    else:
        out = corpus.search_multi([ask["part"], query], 12 if allowed else 4, kinds={"passage"}, per_unit=2, floor=0.2)
        out = [c for c in out if c.project_id in allowed][:4] if allowed else out
    if _OUTCOME.search(ask["part"]) or _STACK.search(ask["part"]):   # results and the tech stack live on the project cards
        for pid in dict.fromkeys(c.project_id for c in out if c.project_id):
            card = kb.card(pid)
            if card:
                out.append(card)
    if _LINK.search(ask["part"]):
        out += _links(kb)
    return out


def _dedupe_chunks(chunks: list[Chunk]) -> list[Chunk]:
    seen, out = set(), []
    for c in chunks:
        if c.id not in seen:
            seen.add(c.id)
            out.append(c)
    return out


def _dedupe_sentences(text: str) -> str:
    seen, out = set(), []
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        key = re.sub(r"\W+", " ", s.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return " ".join(out)


def _title(kb, pid) -> str:
    u = (getattr(kb, "units", {}) or {}).get(pid) if pid else None
    return f"{u.get('title')} ({u.get('org')})" if u else "profile / general"


def build_prompt(question: str, asks: list[dict], blocks: list[tuple[dict, list[Chunk]]], limit=None, kb=None) -> str:
    parts = []
    for n, (ask, chunks) in enumerate(blocks, 1):
        by_project: dict = {}                              # it2: grouped by project so a fact is never moved to another one
        for c in chunks:
            by_project.setdefault(c.project_id or "", []).append(c)
        mat = "\n".join(f"  PROJECT \"{_title(kb, pid)}\":\n" + "\n".join(f"    - {c.text}" for c in cs)   # it3: titles, not ids
                        for pid, cs in by_project.items()) or "  (nothing stored for this ask)"
        parts.append(f"ASK {n} ({ask['source']}): {ask['part']}\n MATERIAL:\n{mat}")
    size = (f"Keep the whole answer under {limit} characters." if limit else
            "About 60-90 words per ask; no padding.")   # it8 tried 40-60: faithfulness +0.05 but coverage -0.06 -> it9 back to 60-90
    return (f"You write a job applicant's answer, in the first person, to this application question:\n\"{question}\"\n\n"
            "Answer EVERY ask below, in the order given, as connected prose (no headings, no numbering, no preamble).\n"
            "Rules:\n"
            "- If an ask is a yes/no question, start that part with Yes or No. When the true answer is a qualified yes (a PoC, "
            "an internal tool, batch rather than real-time), write 'Yes — ' and then the true scope in the same sentence.\n"
            "- Name the specifics the ask wants (model, tools, numbers, the link) when the material states them.\n"
            "- About the applicant, say ONLY what that ask's MATERIAL states: no invented projects, numbers, users, links or outcomes.\n"
            "- Keep every fact with the PROJECT it is listed under; never credit one project with another's work.\n"
            "- State facts in the material's own wording. Do not add qualities or effects it does not state ('reliable', "
            "'efficient', 'accurate', 'ensured', 'prevented', 'improved X') — say what was built and what it did.\n"
            "- Keep the material's own status words. A PoC / prototype / internal tool is NOT 'shipped to production', 'customer-"
            "facing', 'real-time' or 'used by N users' unless the material says so; if the question asks for that, state the true "
            "status plainly (e.g. 'a working PoC deployed on an internal server').\n"
            "- Never answer with a denial ('No, I have not...', 'I have not personally...'). Lead with the strongest real example "
            "and its true status instead; the reader judges the fit.\n"
            "- When an ask wants a link, give the link itself as that ask's answer (e.g. 'My work is on GitHub: <url>').\n"
            "- Refer to projects by their titles, never by internal ids.\n"
            "- A GENERAL ask (how would you / what would you investigate) is answered from sound standard practice.\n"
            "- A COMPANY ask (why this company / what interests you) names one or two specific things the company builds "
            "or has done, from its material, in your own words, and ties them to your work; never restate the job post.\n"
            "- If something an ask needs is not stated, give the closest true thing that is, without inventing the rest.\n"
            "- Never mention 'the material', 'provided information' or what is missing from it. Never repeat a sentence. "
            "Never open with 'Closest example' or any lead-in.\n"
            f"- {size}\n\n" + "\n\n".join(parts) + "\n\nAnswer:")


def _json(raw: str) -> dict:
    import json
    raw = _THINK.sub("", raw or "")
    i = raw.find("{")
    try:
        obj = json.JSONDecoder().raw_decode(raw[i:])[0] if i >= 0 else {}
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def uncovered(text: str, asks: list[dict], llm) -> list[int]:
    """it3: which asks (1-based) no sentence of TEXT answers, as the writer itself reads it. [] when unreadable."""
    listing = "\n".join(f"{n}. {a['part']}" for n, a in enumerate(asks, 1))
    data = _json(llm(f"ANSWER:\n{text}\n\nASKS:\n{listing}\n\nFor each ask, quote the sentence of the ANSWER that directly "
                     'answers it, or "" if none does. Reply with ONLY JSON: {"answers": {"1": "...", "2": "..."}}'))
    got = data.get("answers") if isinstance(data.get("answers"), dict) else {}
    return [n for n in range(1, len(asks) + 1) if got and not str(got.get(str(n)) or "").strip()]


def answer_asks(question: str, *, job, kb, corpus, llm, limit=None, research=None) -> dict:
    """`research` is a ResearchBundle, or a callable returning one (looked up only when an answer needs it)."""
    from .outreach import OUTREACH, answer_outreach, copied_run
    from .segments import invented_links, sub_asks
    get_research = research if callable(research) else (lambda: research)
    if OUTREACH.search(question):
        return answer_outreach(question, job=job, corpus=corpus, research=get_research(), llm=llm, limit=limit)
    asks = sub_asks(question, llm)
    research = get_research() if any(a["source"] == "COMPANY" for a in asks) else None
    pid = project_for(asks, question, corpus) if _ONE_THING.search(question) else None
    # it10 capped a note-to-the-team at the 2 projects that fit the posting: tied with it9 on the same judge
    # (0.94/0.89 both) -> reverted, simpler wins a tie
    allowed = None
    blocks = [(a, material_for(a, question, kb, corpus, pid if a["source"] == "CANDIDATE" else None,
                               allowed if a["source"] == "CANDIDATE" else None, research)) for a in asks]
    chunks = _dedupe_chunks([c for _, cs in blocks for c in cs])
    try:
        raw = llm(build_prompt(question, asks, blocks, limit, kb))
    except Exception as e:
        return {"answer": None, "chunks": chunks, "flags": [f"writer_failed:{type(e).__name__}"], "confidence": None}
    text = _dedupe_sentences(_PREAMBLE.sub("", _THINK.sub("", raw or "")).strip())
    flags, notes = [], []
    posting = [c.text for c in corpus.items if c.kind == "company"]
    copied = copied_run(text, posting) if research is not None else None
    if copied:                                               # a 'why us' that restates the job post: one rewrite
        try:
            again = llm(build_prompt(question, asks, blocks, limit, kb).replace(
                "\n\nAnswer:", f"\n\nDo not reuse the job post's wording such as \"{copied}\".\n\nAnswer:"))
            again = _dedupe_sentences(_PREAMBLE.sub("", _THINK.sub("", again or "")).strip())
            if again:
                text = again
                notes.append("rewrote_job_post_wording")
        except Exception:
            pass
    try:                                                     # it3: coverage repair, one grounded addition per missed ask
        for n in uncovered(text, asks, llm) if text else []:
            ask, mat = blocks[n - 1]
            add = llm(build_prompt(question, [ask], [(ask, mat)], None, kb).replace(
                "Answer EVERY ask below", "Write 1-2 sentences answering ONLY the ask below") + "")
            add = _dedupe_sentences(_PREAMBLE.sub("", _THINK.sub("", add or "")).strip())
            if add:
                text = _dedupe_sentences(f"{text} {add}")
                notes.append(f"repaired:{n}")
    except Exception:
        pass
    if limit and text:                                     # the field's maxlength is a hard cap, whatever the prompt said
        from .verify import fit_length
        text, trimmed = fit_length(text, limit)
        if trimmed:
            notes.append("trimmed_to_limit")
    # it4 tried a fidelity self-check pass by the writer: no faithfulness gain, coverage fell -> removed (see git history)
    known = [str(v) for v in (getattr(kb, "_facts", {}) or {}).values() if isinstance(v, str)]
    bad = invented_links(text, chunks, known)
    if bad:                                                   # a made-up link is never filled
        flags.append("invented_link:" + ",".join(bad))
        return {"answer": None, "chunks": chunks, "flags": flags, "confidence": None, "basis": "held: invented link"}
    # judgment.py fills when confidence clears its gate and no flag is raised; repairs are notes, not problems
    return {"answer": text or None, "chunks": chunks, "flags": flags, "notes": notes, "confidence": 85 if text else None,
            "basis": "ask by ask from your projects: " + "; ".join(a["part"] for a in asks),
            "used": [c.id for c in chunks], "asks": [a["part"] for a in asks], "unsupported_company_claims": []}
