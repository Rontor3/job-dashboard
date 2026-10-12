"""Retrieval strategies compared on the same Corpus. Each returns a Result: the chunks, how many model calls it spent and
how long it took, so quality can be weighed against the time a form takes.

  naive            search the whole corpus with the question as it is
  current          what the pipeline does today: a regex decides "hypothetical" -> practice entries, otherwise project passages
  query_transform  the model rewrites the question into several search queries (one per thing asked + a broader step-back
                   query + a keyword form); results fused with reciprocal-rank fusion                         [1 model call]
  hyde             the model writes a hypothetical answer; the corpus is searched with THAT text, which sits closer to the
                   records than the question does                                                                [1 model call]
  agentic          the model plans which tools to call (overview, work passages, profile, skills, stories, practice, company),
                   reads what came back, and may call more tools once or twice                                 [2-4 model calls]
  qt_hyde          query transformation and HyDE together: the rewritten queries plus the hypothetical answer, fused  [2 calls]"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from .corpus import Corpus
from .kb import Chunk

MAX_CHUNKS = 8
QUESTION_TYPES = {
    "single_project": "asks about ONE project or system the applicant built (problem, build, result)",
    "work_summary": "asks to summarise the applicant's work, or 'tell us about yourself / what you're looking for'",
    "generic_experience": "asks about experience with a topic across their work (e.g. ML in production)",
    "skills": "asks to list skills or tools",
    "role_message": "a message to a team about fit for THIS role and company",
    "motivation": "why this company / what interests them about it",
    "method": "a hypothetical or best-practice question about a SITUATION or SYSTEM ('how would you design/handle...', 'suppose...', 'you inherit...')",
    "technical_knowledge": "a technical interview question: explain a concept, compare techniques, define a term, how something works (no personal data needed)",
    "mixed": "asks for a past example AND the standard method or metric",
}
_HYP = re.compile(r"\b(how would you|suppose|imagine|you inherit|what would you|if you (?:were|had))\b", re.I)
_EXP = re.compile(r"\b(have you|did you|you(?:'ve| have)? (?:personally )?(?:built|shipped|used|led|implemented|designed|worked|run|ran)"
                  r"|your (?:experience|work|project)|tell us about a time|describe a (?:time|project))\b", re.I)


@dataclass
class Result:
    chunks: list[Chunk]
    calls: int = 0
    seconds: float = 0.0
    trace: list[str] = field(default_factory=list)


class Counted:
    """Wraps a model callable: counts calls and the time they take."""
    def __init__(self, fn):
        self.fn, self.calls, self.seconds = fn, 0, 0.0

    def __call__(self, prompt: str) -> str:
        t = time.time()
        try:
            return self.fn(prompt)
        finally:
            self.calls += 1
            self.seconds += time.time() - t


def _json(raw: str) -> dict:
    m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S), flags=re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _dedupe(chunks: list[Chunk], limit: int = MAX_CHUNKS) -> list[Chunk]:
    seen, out = set(), []
    for c in chunks:
        if c.id not in seen:
            seen.add(c.id)
            out.append(c)
    return out[:limit]


def _run(fn):
    """Decorator: time the method and count the model calls it made through the Counted llm."""
    def wrapper(question, corpus, llm, *a, **k):
        llm = llm if isinstance(llm, Counted) else Counted(llm)
        before_calls, before_secs, t = llm.calls, llm.seconds, time.time()
        chunks, trace = fn(question, corpus, llm, *a, **k)
        return Result(_dedupe(chunks), llm.calls - before_calls, time.time() - t, trace)
    wrapper.__name__ = fn.__name__
    return wrapper


@_run
def naive(question, corpus, llm):
    return corpus.search(question, MAX_CHUNKS, per_unit=3), ["search(question)"]


@_run
def current(question, corpus, llm):
    """The pipeline as it runs today (segments.answer_segmented): a regex gate for hypotheticals, otherwise the passages of ONE
    project, the one that owns the best-ranked passages for the whole question (kb.main_project)."""
    if _HYP.search(question) and not _EXP.search(question):
        return corpus.search(question, 2, kinds={"practice"}), ["regex: hypothetical -> practice"]
    main = corpus.kb.main_project(question)
    return corpus.kb.passages(question, 5, project_id=main), [f"personal -> one project: {main}"]


@_run
def query_transform(question, corpus, llm):
    prompt = ("Rewrite this job-application question into search queries for finding evidence in the applicant's records "
              "(project write-ups, profile, skills, own-words stories, general best-practice notes, the job posting).\n"
              f'QUESTION: "{question}"\n\nGive 3 or 4 queries:\n'
              "1-2. one query per distinct thing the question asks for, phrased as the evidence you would look for\n"
              "3. a broader step-back query naming the general topic\n"
              "4. a keyword-only query\n"
              'Reply with ONLY JSON: {"queries": ["...", "..."]}')
    qs = [q for q in (_json(llm(prompt)).get("queries") or []) if isinstance(q, str) and q.strip()][:4]
    qs = qs or [question]
    return corpus.search_multi(qs, MAX_CHUNKS, per_unit=2), [f"query: {q[:70]}" for q in qs]


def _hypothetical(question: str, llm) -> str:
    prompt = ("Write a short plausible answer (about 80 words, first person) to this job-application question, as a strong "
              "candidate would. It does not have to be true: it will only be used to look up similar real records.\n"
              f'QUESTION: "{question}"\n\nAnswer:')
    return re.sub(r"<think>.*?</think>", "", llm(prompt) or "", flags=re.S).strip()[:900]


@_run
def hyde(question, corpus, llm):
    doc = _hypothetical(question, llm)
    return corpus.search(doc or question, MAX_CHUNKS, per_unit=3), [f"hyde: {doc[:90]!r}"]


@_run
def qt_hyde(question, corpus, llm):
    qt_prompt = ("Rewrite this job-application question into 3 search queries for finding evidence in the applicant's records: "
                 "one per distinct thing asked, plus one broader step-back query.\n"
                 f'QUESTION: "{question}"\nReply with ONLY JSON: {{"queries": ["...", "..."]}}')
    qs = [q for q in (_json(llm(qt_prompt)).get("queries") or []) if isinstance(q, str) and q.strip()][:3] or [question]
    doc = _hypothetical(question, llm)
    return corpus.search_multi(qs + ([doc] if doc else []), MAX_CHUNKS, per_unit=2), [f"query: {q[:60]}" for q in qs] + [f"hyde: {doc[:70]!r}"]


# --- agentic ----------------------------------------------------------------------------------------------------------

TOOLS = {
    "overview": "one best passage of EVERY project and job (breadth across all the applicant's work). No query.",
    "search_work": "passages from the applicant's projects / jobs that match a query (depth).",
    "profile": "current role, years of experience, education. No query.",
    "skills": "the applicant's skills list. No query.",
    "stories": "the applicant's own-words answers (what they look for, why startups, how they work) matching a query.",
    "practice": "industry-standard best practice for a method / hypothetical question, matching a query.",
    "company": "pieces of the job posting being applied to, matching a query.",
}


def _tool(corpus: Corpus, name: str, query: str) -> list[Chunk]:
    q = query or ""
    if name == "overview":
        return corpus.overview()
    if name == "search_work":
        return corpus.search(q, 4, kinds={"passage"}, per_unit=2, floor=0.25)
    if name == "profile":
        return corpus.facts()
    if name == "skills":
        return corpus.by_id("fact:skills")
    if name == "stories":
        return corpus.search(q, 2, kinds={"story"}, floor=0.1)
    if name == "practice":
        return corpus.search(q, 2, kinds={"practice"}, floor=0.1)
    if name == "company":
        return corpus.search(q, 2, kinds={"company"}, floor=0.05)
    return []


def _calls_from(data: dict, limit: int) -> list[dict]:
    out = []
    for c in data.get("calls") or []:
        if isinstance(c, dict) and c.get("tool") in TOOLS:
            out.append({"tool": c["tool"], "query": str(c.get("query") or "")[:200]})
    return out[:limit]


@_run
def agentic(question, corpus, llm, max_rounds: int = 2):
    tools = "\n".join(f"- {k}: {v}" for k, v in TOOLS.items())
    types = "\n".join(f"- {k}: {v}" for k, v in QUESTION_TYPES.items())
    plan_prompt = (f"You plan retrieval for a job-application answer.\nQUESTION: \"{question}\"\n\n"
                   f"Question types:\n{types}\n\nTools:\n{tools}\n\n"
                   "First decide the question type. Then list the tool calls that fetch exactly the information the answer needs "
                   "(1 to 4 calls). Use overview for 'summarise my work' style questions, search_work for one project, practice for "
                   "'how would you' questions (and no personal tools for them), profile/skills for who-I-am questions, company for "
                   "questions about this role or employer.\n"
                   'Reply with ONLY JSON: {"type": "...", "calls": [{"tool": "...", "query": "..."}]}')
    plan = _json(llm(plan_prompt))
    calls, trace, got = _calls_from(plan, 4), [f"type={plan.get('type')}"], []
    for _ in range(max_rounds):
        for c in calls:
            got += _tool(corpus, c["tool"], c["query"] or question)
            trace.append(f"{c['tool']}({c['query'][:50]})")
        got = _dedupe(got, 12)
        if _ == max_rounds - 1:
            break
        seen = "\n".join(f"- {c.id} [{c.kind}] {c.text[:80]}" for c in got) or "(nothing yet)"
        reflect = (f"QUESTION: \"{question}\"\n\nRETRIEVED SO FAR:\n{seen}\n\n"
                   "Is anything the answer needs still missing (a part of the question with no evidence, or evidence that is "
                   "off-topic and should be ignored)? If everything is covered reply {\"done\": true}. Otherwise reply "
                   f'{{"calls": [{{"tool": "...", "query": "..."}}]}} with at most 2 more tool calls from: {", ".join(TOOLS)}.')
        data = _json(llm(reflect))
        calls = [] if data.get("done") else _calls_from(data, 2)
        if not calls:
            trace.append("reflect: done")
            break
        trace.append("reflect: more")
    return got, trace


# --- routed: classify the question once, then a fixed retrieval policy per type --------------------------------------------

def classify(question: str, llm) -> str:
    types = "\n".join(f"- {k}: {v}" for k, v in QUESTION_TYPES.items())
    prompt = (f'Classify this job-application question into exactly ONE type.\nQUESTION: "{question}"\n\nTypes:\n{types}\n\n'
              'Examples: "Explain how attention works" / "difference between bagging and boosting" / "what is overfitting" = technical_knowledge; '
              '"Tell us about the project you are proudest of" = single_project; "Give us an overview of your background" = '
              'work_summary; "Do you have experience with X?" = generic_experience; "How would you design X?" = method; '
              '"Tell us about a time you improved X and how you measured it" = mixed.\n'
              'Reply with ONLY JSON: {"type": "<one of the types>"}')
    t = _json(llm(prompt)).get("type")
    return t if t in QUESTION_TYPES else ""


def policy(qtype: str, question: str, corpus: Corpus) -> list[Chunk]:
    """What to fetch for each question type. No model calls."""
    kb = corpus.kb
    if qtype == "single_project":                      # depth in ONE project: the one that owns the best passages for the whole question
        return kb.passages(question, 5, project_id=kb.main_project(question))
    if qtype == "work_summary":                        # breadth: the best passage of EVERY project + who I am + one own-words story
        return corpus.overview() + corpus.facts() + corpus.search(question, 1, kinds={"story"}, floor=0.05)
    if qtype == "generic_experience":                  # breadth on a topic: different projects, two passages each at most, plus who I am
        return corpus.search(question, 6, kinds={"passage"}, per_unit=2, floor=0.2) + corpus.facts()[:1]
    if qtype == "skills":
        return corpus.by_id("fact:skills") + corpus.facts()[:1]
    if qtype == "motivation":                          # the employer's own words, my own words, one build that fits
        return (corpus.search(question, 2, kinds={"company"}, floor=0.0) + corpus.search(question, 2, kinds={"story"}, floor=0.05)
                + corpus.search(question, 1, kinds={"passage"}, floor=0.2))
    if qtype == "role_message":                        # who I am + DIFFERENT builds that fit + what the role/company says + own motivation
        return (corpus.facts()[:1] + corpus.search(question, 3, kinds={"passage"}, per_unit=1, floor=0.2)
                + corpus.search(question, 2, kinds={"company"}, floor=0.0) + corpus.search(question, 1, kinds={"story"}, floor=0.05))
    if qtype == "method":                              # general knowledge only: a practice note ONLY if one really matches, never a forced pick
        return corpus.close(question, 2, kinds={"practice"})
    if qtype == "technical_knowledge":                 # answered from knowledge; at most one real link to the applicant's own work
        return corpus.close(question, 1, kinds={"passage"})
    if qtype == "mixed":                               # the standard method + the applicant's own matching evidence
        return corpus.close(question, 1, kinds={"practice"}) + corpus.search(question, 3, kinds={"passage"}, per_unit=2, floor=0.2)
    return corpus.search(question, MAX_CHUNKS, per_unit=3)


@_run
def routed(question, corpus, llm):
    qtype = classify(question, llm)
    return policy(qtype, question, corpus), [f"type={qtype or 'unknown -> naive search'}"]


METHODS = {"naive": naive, "current": current, "query_transform": query_transform, "hyde": hyde, "agentic": agentic, "qt_hyde": qt_hyde,
           "routed": routed}
