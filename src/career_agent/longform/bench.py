"""Labelled test set and scoring for comparing retrieval strategies. Scores come from LABELS (which records a good answer to
this kind of question must draw on), not from a model, so a method cannot grade its own work.

Shapes (what good retrieval looks like for the question type):
  one      one project must dominate (the right one)          score = .4 dominant + .4 share-from-expected + .2 no-noise
  one_any  one project must dominate, any project              score = .5 dominant + .5 no-noise
  many     breadth: >= k DIFFERENT expected projects           score = .7 coverage + .3 no-noise
  role     fit for a role: an expected project, 2+ projects,   score = .5 hit + .25 breadth + .25 company posting present
           and the posting itself
  facts    the skills list                                     score = .8 present + .2 no-noise
  motive   own-words story AND the posting                     score = .4 story + .4 posting + .2 no-noise
  none     general knowledge: the right practice entry, no     score = .6 practice + .4 (1 - personal share)
           personal records
  mixed    a past example AND the standard method              score = .5 practice + .5 personal evidence
  tech     a technical-knowledge question: NO unrelated practice  score = .5 (no practice notes) + .5 personal link if the question
           notes; a project link only if one is genuinely related           really relates to a project, else .5 (no personal records)
"""
from __future__ import annotations

from dataclasses import dataclass, field

HF, MD, GR, PE = ("tata-health-fraud-pipeline", "tata-medical-fraud-doc-scoring", "tata-graph-ml-fraud-rings",
                  "tata-passive-equity-optimization")
PROJECTS = {HF, MD, GR, PE}
PERSONAL = {"passage", "fact", "story"}


@dataclass
class Case:
    id: str
    type: str
    shape: str
    question: str
    job_id: int | None = None
    expect: set = field(default_factory=set)         # expected project ids
    allowed: set = field(default_factory=lambda: {"passage"})
    k: int = 1
    practice: str | None = None                      # expected practice id


CASES = [
    Case("c01", "single_project", "one", "What is the most technically complex AI/LLM system you have personally built and shipped to production? Briefly describe it and what was hardest.", expect={MD}, allowed={"passage", "story"}),
    Case("c02", "single_project", "one", "Describe a customer-facing AI product you personally shipped. What user problem did it solve, what did you build, and what happened after launch?", expect={HF, MD}, allowed={"passage", "story"}),
    Case("c03", "single_project", "one", "Have you deployed an LLM application to end-users that runs in real-time? What was the primary model and use case?", expect={MD}, allowed={"passage"}),
    Case("c04", "single_project", "one_any", "Share a working product, demo, repository, or technical write-up. Identify your contribution.", allowed={"passage", "story"}),
    Case("c05", "work_summary", "many", "Start a conversation with the team. Share something about you, what you're looking for, or why you're interested in working with them.", expect=PROJECTS, allowed={"passage", "fact", "story"}, k=3),
    Case("c06", "work_summary", "many", "Tell us about yourself and the kinds of problems you have worked on.", expect=PROJECTS, allowed={"passage", "fact", "story"}, k=3),
    Case("c07", "work_summary", "many", "Summarize your professional experience.", expect=PROJECTS, allowed={"passage", "fact"}, k=3),
    Case("c08", "generic_experience", "many", "What is your experience with machine learning in production?", expect={HF, MD, PE, GR}, allowed={"passage", "fact"}, k=2),
    Case("c09", "skills", "facts", "Please list down your skillset", allowed={"fact"}),
    Case("c10", "motivation", "motive", "What interests you about working for this company?", job_id=30278, allowed={"story", "company", "passage"}),
    Case("c11", "role_message", "role", "Reach out to the founders at Veryfi, Inc.. In a short message, tell them a little about yourself, what you have built that is relevant to the Data Scientist - Fraud Detection role, and why you want to work on Veryfi, Inc..", job_id=29161, expect={HF, MD, GR}),
    Case("c12", "role_message", "role", "Reach out to the founders at Knowtex. In a short message, tell them a little about yourself, what you have built that is relevant to the ML Engineer: Speech & LLMs role, and why you want to work on Knowtex.", job_id=30122, expect={MD}),
    Case("c13", "method", "none", "You inherit a production RAG agent with 90% retrieval recall but poor answer quality. What would you investigate first?", practice="rag_quality_debug"),
    Case("c14", "method", "none", "Suppose an AI agent needs to remember a business's important information across 6 months of conversations. How would you design its memory system?", practice="agent_memory"),
    Case("c15", "mixed", "mixed", "How have you evaluated whether an LLM/RAG/agent system actually improved? Give one example of a metric, test set, or evaluation process you have used.", expect={HF}, practice="llm_eval"),
]


def _share(n: int, d: int) -> float:
    return n / d if d else 0.0


def score_case(case: Case, chunks) -> dict:
    ids = [c.id for c in chunks]
    passages = [c for c in chunks if c.kind == "passage"]
    units = [c.project_id for c in passages]
    distinct = len(set(units))
    noise = _share(sum(1 for c in chunks if c.kind not in case.allowed), len(chunks))
    top = max(set(units), key=units.count) if units else None
    dominant_share = _share(units.count(top), len(units)) if units else 0.0
    has_company = any(c.kind == "company" for c in chunks)
    has_story = any(c.kind == "story" for c in chunks)
    personal_share = _share(sum(1 for c in chunks if c.kind in PERSONAL), len(chunks))
    practice_hit = bool(case.practice) and f"practice:{case.practice}" in ids
    s = case.shape
    if not chunks and s != "tech":
        score = 0.0
    elif s == "one":
        score = .4 * (top in case.expect) + .4 * _share(sum(1 for u in units if u in case.expect), len(chunks)) + .2 * (1 - noise)
    elif s == "one_any":
        score = .5 * (dominant_share >= 0.6 and bool(units)) + .5 * (1 - noise)
    elif s == "many":
        score = .7 * min(1.0, len(set(units) & case.expect) / case.k) + .3 * (1 - noise)
    elif s == "role":
        score = .5 * bool(set(units) & case.expect) + .25 * (distinct >= 2) + .25 * has_company
    elif s == "facts":
        score = .8 * ("fact:skills" in ids) + .2 * (1 - noise)
    elif s == "motive":
        score = .4 * has_story + .4 * has_company + .2 * (1 - noise)
    elif s == "none":
        score = .6 * practice_hit + .4 * (1 - personal_share)
    elif s == "mixed":
        score = .5 * practice_hit + .5 * bool(set(units) & case.expect)
    elif s == "tech":
        no_practice = not any(c.kind == "practice" for c in chunks)
        personal = [c for c in chunks if c.kind in PERSONAL]
        link = bool(set(units) & case.expect) if case.expect else not personal
        score = .5 * no_practice + .5 * link
    else:
        score = 0.0
    return {"score": round(float(score), 4), "noise": round(noise, 3), "distinct_projects": distinct,
            "top_project": top, "dominant_share": round(dominant_share, 3), "ids": ids}


# Written BEFORE the routed method was run, with new wordings and other jobs: the fair test of a design that was shaped by CASES.
HELD_OUT = [
    Case("h01", "single_project", "one_any", "Tell us about the project you are most proud of and why.", allowed={"passage", "story"}),
    Case("h02", "single_project", "one", "Describe a time you reduced hallucinations in an LLM system.", expect={MD}, allowed={"passage"}),
    Case("h03", "single_project", "one", "Tell me about a machine learning model you deployed to production and how you handled real-time scoring.", expect={HF}, allowed={"passage"}),
    Case("h04", "work_summary", "many", "Give us a brief overview of your background.", expect=PROJECTS, allowed={"passage", "fact", "story"}, k=3),
    Case("h05", "work_summary", "many", "What have you been working on lately?", expect=PROJECTS, allowed={"passage", "fact"}, k=3),
    Case("h06", "generic_experience", "many", "Do you have experience with fraud detection? Tell us about it.", expect={HF, MD, GR}, allowed={"passage", "fact"}, k=2),
    Case("h07", "skills", "facts", "What are your core technical skills?", allowed={"fact"}),
    Case("h08", "motivation", "motive", "Why do you want to join us?", job_id=29161, allowed={"story", "company", "passage"}),
    Case("h09", "role_message", "role", "Write a note to the hiring manager about why you are a fit for the Applied AI Engineer role.", job_id=29132, expect={HF, MD, GR}),
    Case("h10", "method", "none", "How would you evaluate a RAG system before launching it to customers?", practice="llm_eval"),
    Case("h11", "method", "none", "What is your approach to making an AI agent reliable once it is in production?", practice="agent_productionization"),
    Case("h12", "mixed", "mixed", "Tell us about a time you improved model quality and how you measured the improvement.", expect={HF}, practice="llm_eval"),
]


# Technical-interview questions: added after seeing the router fetch unrelated practice notes for them; the practice cut-off was
# calibrated on separate similarity measurements, but these are NOT a blind test.
TECH = [
    Case("t01", "technical_knowledge", "tech", "What is the difference between bagging and boosting, and when would you pick each?", expect={HF}),
    Case("t02", "technical_knowledge", "tech", "Explain how the attention mechanism in a transformer works."),
    Case("t03", "technical_knowledge", "tech", "How does a gradient boosted tree handle class imbalance, and what would you tune first?", expect={HF}),
    Case("t04", "technical_knowledge", "tech", "What is the bias-variance tradeoff?"),
    Case("t05", "technical_knowledge", "tech", "How would you handle missing values in a dataset?"),
    Case("t06", "technical_knowledge", "tech", "What is the difference between a process and a thread?"),
]
