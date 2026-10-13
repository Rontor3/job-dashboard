"""Briefed answers: read the question, decide what KIND of information each part of the answer needs, give each part its own
material and its own instructions (what it is answering, how big it should be, what not to do), then assemble.

Why: a question rarely asks for one thing. "Tell them a little about yourself, what you have built that is relevant to the
role, and why you want to work on us" needs (1) a brief introduction, (2) two or three DIFFERENT builds matched to what
this job requires, (3) one company-specific reason. Feeding the writer one project's passages produces one project told at
length. So every segment has a TYPE, and the type decides the material, the size, and the prohibitions.

  intro            who the applicant is: facts only, brief                     -> profile facts
  relevant_builds  2-3 different builds, each matched to a requirement of THIS job -> job requirements x project records
  why_company      one company-specific reason                                 -> company facts from the posting + own motivation
  project_story    ONE project in depth (the question asks for one)           -> passages of one project
  method           how one would do something (hypothetical / best practice)  -> practice library
  preference       what the applicant wants / how they work                   -> own-words stories
  other            anything else                                              -> own-words stories + best passages

Same return shape as segments.answer_segmented."""
from __future__ import annotations

import re

from .kb import Chunk, tokens
from .segments import (_EXP, _HYP, _clean, _is_gap, _json, _strip_number, invented_links, supported)

PLACEHOLDER = re.compile(r"\[[A-Za-z][^\]]{2,60}\]|\{\{[^}]+\}\}|<[A-Z][^>]{2,40}>")

TYPES = {
    "intro": {
        "purpose": "Introduce the applicant briefly: who they are, how long they have worked, where, and a few of their strongest "
                   "skills for this role.",
        "size": "1-2 sentences, at most 40 words",
        "avoid": "Do not describe any project. Do not list more than five skills. Say nothing that is not in the FACTS.",
        "words": 45},
    "relevant_builds": {
        "purpose": "Show what the applicant has built that matches what THIS role needs. Name two or three DIFFERENT builds, one short "
                   "clause each, and say which requirement each one answers.",
        "size": "2-3 sentences, at most 75 words in total",
        "avoid": "Do not tell one build at length. Do not use a build that does not match a requirement. Use only the results "
                 "listed. Do not mention a build twice.",
        "words": 80},
    "why_company": {
        "purpose": "Say why the applicant wants to work on THIS company: connect one thing the company does to something the "
                   "applicant cares about.",
        "size": "1-2 sentences, at most 40 words",
        "avoid": "No generic praise ('innovative', 'cutting-edge', 'passionate'). Mention only what the COMPANY FACTS say. Do not "
                 "describe a project.",
        "words": 45},
    "project_story": {
        "purpose": "Tell ONE project in depth, in the order the question asks (problem, what was built, hardest part, result).",
        "size": "4-6 sentences",
        "avoid": "Use only this project. Copy its facts almost word for word and add no detail.",
        "words": 130},
    "method": {
        "purpose": "Write the concrete plan or method in first person ('I would...'), in practitioner order, covering everything "
                   "this part asks.",
        "size": "3-6 sentences",
        "avoid": "This is general practice: never claim the applicant did it.",
        "words": 130},
    "preference": {
        "purpose": "Say what the applicant wants or how they work, from their own words.",
        "size": "1-3 sentences",
        "avoid": "Use only the OWN WORDS. Do not describe a project.",
        "words": 70},
    "other": {
        "purpose": "Answer this part of the question directly.",
        "size": "2-4 sentences",
        "avoid": "Use only the material. Do not describe a project unless it is asked for.",
        "words": 80},
}
_GLOBAL_AVOID = ("Never leave a placeholder such as [Name]. Never invent a fact, number, link or project. Do not restate the question. "
                 "No headings or bullet points.")


# --- 1. read the question ---------------------------------------------------------------------------------------------

def _format_of(question: str, company: str) -> dict:
    """Message shape from the wording: a greeting for 'reach out to the founders at X', a word cap for 'short message'."""
    q = _strip_number(question)
    fmt = {"greeting": None, "max_words": None}
    m = re.search(r"\breach out to (?:the )?(founders?|hiring team|team|recruiter|hiring manager)s?(?: at ([\w .&'-]+?))?(?:[.,:]|$| in )", q, re.I)
    if m:
        who = m.group(1).lower()
        org = (m.group(2) or company or "").strip()
        fmt["greeting"] = f"Hi {org} {who}," if org else f"Hi {who},"
    if re.search(r"\b(short|brief) (message|note|email|intro)\b", q, re.I):
        fmt["max_words"] = 120
    return fmt


def analyse(question: str, llm) -> list[dict]:
    """[{part, type, quote}] in the order asked. The model reads the question; code checks each quote is really in it."""
    if _HYP.search(question) and not _EXP.search(question):
        return [{"part": _strip_number(question), "type": "method", "quote": _strip_number(question)}]
    prompt = (
        "Read this job-application question and split it into the separate parts of the ANSWER, in the order asked. Give each part a TYPE:\n"
        "- intro: 'tell us about yourself' (a brief self-introduction)\n"
        "- relevant_builds: 'what have you built that is relevant to this role' (several short builds matched to the job)\n"
        "- why_company: 'why do you want to work here / on this company'\n"
        "- project_story: 'describe ONE project / system you built' in depth\n"
        "- method: 'how would you...' / best practice / a plan\n"
        "- preference: what you want, how you work\n"
        "- other: anything else\n"
        "Each part needs a 'quote': the exact words of the question that ask for it. Do not add parts the question does not ask for.\n\n"
        "EXAMPLE 1\nQUESTION: Reach out to the founders at Acme. In a short message, tell them a little about yourself, what you have "
        "built that is relevant to the Data Scientist role, and why you want to work on Acme.\n"
        '{"segments": [{"part": "a little about yourself", "type": "intro", "quote": "tell them a little about yourself"}, '
        '{"part": "what you built that is relevant to the role", "type": "relevant_builds", "quote": "what you have built that is relevant to the Data Scientist role"}, '
        '{"part": "why you want to work on the company", "type": "why_company", "quote": "why you want to work on Acme"}]}\n\n'
        "EXAMPLE 2\nQUESTION: Describe a customer-facing product you shipped. What problem did it solve, and what happened after launch?\n"
        '{"segments": [{"part": "one shipped product: problem, build, outcome", "type": "project_story", "quote": "Describe a customer-facing product you shipped"}]}\n\n'
        f'NOW\nQUESTION: {question}\nReply with ONLY JSON in the same shape.')
    try:
        rows = _json(llm(prompt)).get("segments")
    except Exception:
        rows = None
    qwords = set(re.findall(r"[a-z0-9]+", question.lower()))
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or r.get("type") not in TYPES or not isinstance(r.get("part"), str) or not r["part"].strip():
            continue
        quote = set(re.findall(r"[a-z0-9]+", str(r.get("quote") or "").lower()))
        if len(quote) >= 2 and quote <= qwords:
            out.append({"part": r["part"].strip()[:140], "type": r["type"], "quote": str(r["quote"])[:200]})
    return out[:5] or [{"part": _strip_number(question), "type": "other", "quote": _strip_number(question)}]


# --- 2. what the JOB needs and what the COMPANY does (from the posting only) ------------------------------------------

def _from_posting(kind: str, job: dict, llm, n: int) -> list[str]:
    jd = (job.get("description") or "")[:3500]
    if not jd.strip():
        return []
    what = ("the key requirements of this role (skills, tools, responsibilities)" if kind == "requirements"
            else "what the COMPANY itself does or aims to do (product, customers, mission), NOT the role's requirements")
    prompt = (f"From this job posting, list up to {n} items: {what}. Each item is a short phrase with a 'quote' copied exactly from the posting.\n\n"
              f"POSTING ({job.get('company', '')}, {job.get('title', '')}):\n{jd}\n\n"
              'Reply with ONLY JSON: {"items": [{"item": "short phrase", "quote": "exact words from the posting"}]}')
    try:
        rows = _json(llm(prompt)).get("items")
    except Exception:
        rows = None
    words = set(re.findall(r"[a-z0-9]+", jd.lower()))
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and isinstance(r.get("item"), str) and r["item"].strip():
            q = set(re.findall(r"[a-z0-9]+", str(r.get("quote") or "").lower()))
            if len(q) >= 2 and q <= words:
                out.append(r["item"].strip()[:140])
    return out[:n]


def job_requirements(job: dict, llm) -> list[str]:
    return _from_posting("requirements", job, llm, 6)


def company_facts(job: dict, llm) -> list[str]:
    return _from_posting("company", job, llm, 3)


# --- 3. material per segment type -------------------------------------------------------------------------------------

def _builds_for(requirements: list[str], kb, question: str, n: int = 3) -> list[tuple[str, list[str]]]:
    """Up to `n` DIFFERENT projects, each with the requirements it best answers. Greedy: the best project per requirement."""
    chosen: dict[str, list[str]] = {}
    for req in requirements:
        ranked = kb.rank_projects(req)
        if ranked and ranked[0][1] >= 0.3:
            chosen.setdefault(ranked[0][0], []).append(req)
    if len(chosen) < 2:                                              # too few requirements matched: fall back on the question
        for pid, score in kb.rank_projects(question):
            if score > 0 and pid not in chosen:
                chosen[pid] = []
            if len(chosen) >= 2:
                break
    order = sorted(chosen, key=lambda p: -len(chosen[p]))
    return [(p, chosen[p]) for p in order[:n]]


def _unit_line(u: dict) -> str:
    impact = "; ".join(u.get("impact") or [])[:220] if isinstance(u.get("impact"), list) else str(u.get("impact") or "")[:220]
    what = (u.get("approach") or u.get("problem") or "")[:200]
    return f"{u.get('title', '')} ({u.get('org', '')}): {what}. Results: {impact}"


def _intro_facts(kb, job: dict, requirements: list[str]) -> str:
    f = {k: v for k, v in (kb._facts or {}).items() if isinstance(v, (str, int)) and str(v).strip()}
    lines = []
    if f.get("full_name"):
        lines.append(f"Name: {f['full_name']}")
    for u in kb.units.values():
        if u.get("type") == "work_experience" and str(u.get("to", "")).lower() == "present":
            lines.append(f"Current role: {u.get('title')} at {u.get('org')} since {u.get('from')}")
    if f.get("years_experience"):
        lines.append(f"Experience: {f['years_experience']} years in data science")
    for u in kb.units.values():
        if u.get("type") == "education":
            lines.append(f"Education: {u.get('title')} in {u.get('field')}, {u.get('org')}")
    jd = " ".join(requirements).lower() + " " + (job.get("description") or "").lower()
    skills = [s for s in kb.skills if s.lower() in jd] or kb.skills
    lines.append("Strongest skills for this role: " + ", ".join(skills[:5]))
    return "\n".join(lines)


def material_for(seg: dict, question: str, kb, job: dict, ctx: dict, llm) -> list[Chunk]:
    t = seg["type"]
    if t == "intro":
        return [Chunk("facts:intro", "fact", _intro_facts(kb, job, ctx["requirements"]))]
    if t == "relevant_builds":
        out = []
        for i, (pid, reqs) in enumerate(_builds_for(ctx["requirements"], kb, question), 1):
            tag = f"matches: {'; '.join(reqs)}" if reqs else "closest available build for this role"
            out.append(Chunk(f"build:{pid}", "build", f"BUILD {i} [{tag}] {_unit_line(kb.units[pid])}", pid))
        if ctx["requirements"]:
            out.insert(0, Chunk("requirements", "jd", "WHAT THIS ROLE NEEDS: " + "; ".join(ctx["requirements"])))
        return out
    if t == "why_company":
        own = [c.text[:240] for c in (kb.get_story("story_looking_for"), kb.get_story("story_why_startups")) if c]
        facts = ctx["company_facts"]
        out = [Chunk("company_facts", "company", "COMPANY FACTS: " + ("; ".join(facts) if facts else "(none found in the posting)"))]
        out.append(Chunk("own_motivation", "story_slot", "WHAT THE APPLICANT CARES ABOUT (own words): " + " ".join(own)))
        return out
    if t == "project_story":
        main = kb.main_project(question)
        return kb.passages(question, 5, project_id=main)
    if t == "method":
        return kb.practice_chunks(f"{seg['part']} {question}", 2)
    from .segments import material as base_material
    return base_material({"source": "PREFERENCE" if t == "preference" else "GENERAL", "part": seg["part"]}, question, kb, job.get("description") or "")


# --- 4. one brief per segment -> one piece of text --------------------------------------------------------------------

def _render(chunks: list[Chunk]) -> str:
    return "\n".join(f"[{c.kind.upper()}] {c.text}" for c in chunks) or "(no written material)"


def brief_for(seg: dict, question: str, job: dict) -> str:
    spec = TYPES[seg["type"]]
    who = f"{job.get('title', 'the role')} at {job.get('company', 'the company')}"
    return (f"You are writing ONE part of a job-application answer.\n"
            f"THE WHOLE QUESTION (for context only): {question}\n"
            f"THIS PART: {seg['part']}   [type: {seg['type']}; role: {who}]\n"
            f"WHAT THIS PART MUST DO: {spec['purpose']}\n"
            f"SIZE: {spec['size']}.\n"
            f"DO NOT: {spec['avoid']} {_GLOBAL_AVOID}\n")


def write_segment(seg: dict, chunks: list[Chunk], question: str, job: dict, llm, tighter: bool = False) -> str:
    prompt = (brief_for(seg, question, job) + ("Be shorter than before: stay strictly inside SIZE.\n" if tighter else "")
              + f"\nMATERIAL (use only this):\n{_render(chunks)}\n\nWrite the part now, first person, plain text:")
    try:
        return _clean(llm(prompt))
    except Exception:
        return "GAP"


def _ok(text: str, seg: dict, chunks: list[Chunk], llm, known) -> bool:
    if _is_gap(text) or PLACEHOLDER.search(text) or invented_links(text, chunks, known):
        return False
    if len(text.split()) > TYPES[seg["type"]]["words"] * 1.6:
        return False
    if seg["type"] in ("intro", "relevant_builds", "project_story"):
        return supported(text, chunks, llm)
    return True


def answer_briefed(question, *, job, kb, llm, limit=None) -> dict:
    job = job if isinstance(job, dict) else {}
    known = [str(v) for v in (kb._facts or {}).values() if isinstance(v, str)]
    segs = analyse(question, llm)
    types = {s["type"] for s in segs}
    ctx = {"requirements": job_requirements(job, llm) if "relevant_builds" in types or "intro" in types else [],
           "company_facts": company_facts(job, llm) if "why_company" in types else []}
    fmt = _format_of(question, job.get("company", ""))
    pieces, chunks_all, rows = [], [], []
    for sg in segs:
        chunks = material_for(sg, question, kb, job, ctx, llm)
        text = write_segment(sg, chunks, question, job, llm)
        if not _ok(text, sg, chunks, llm, known):
            text = write_segment(sg, chunks, question, job, llm, tighter=True)
            if not _ok(text, sg, chunks, llm, known):
                text = "GAP"
        gap = _is_gap(text)
        pieces.append((sg, text))
        chunks_all += [c for c in chunks if c.id not in {x.id for x in chunks_all}]
        rows.append({"type": sg["type"], "part": sg["part"], "chunks": [c.id for c in chunks], "gap": gap, "text": text})
    body = " ".join(t.strip() for sg, t in pieces if not _is_gap(t))
    if fmt["max_words"] and len(body.split()) > fmt["max_words"]:          # over the message size: cut whole sentences from the end
        sents, kept = re.split(r"(?<=[.!?])\s+", body), []
        for s in sents:
            if len((" ".join(kept + [s])).split()) <= fmt["max_words"]:
                kept.append(s)
        body = " ".join(kept) or body
    answer = (fmt["greeting"] + " " + body).strip() if fmt["greeting"] and body else body
    flags = ["gap:" + r["part"][:60] for r in rows if r["gap"]]
    held = any(r["gap"] and r["type"] in ("intro", "relevant_builds", "project_story") for r in rows)
    return {"answer": answer or None, "flags": flags, "unsupported_company_claims": [], "confidence": None if (held or not answer) else 85,
            "basis": "briefed; one brief per segment", "prompt": "", "needs": [r["type"] for r in rows], "project_id": None,
            "used": [c.id for c in chunks_all], "plan_source": "brief", "plan_reason": "; ".join(f"{r['type']}: {r['part'][:50]}" for r in rows),
            "segments": rows, "chunks": chunks_all, "requirements": ctx["requirements"], "company_facts": ctx["company_facts"], "format": fmt}
