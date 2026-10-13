"""Writer: one model call that sees ONLY the retrieved chunks. Projects that were not retrieved are not in the
prompt, so they cannot be blended into the answer."""
from __future__ import annotations

from job_dashboard.apply.screening import _parse_reply

_LABELS = {"card": "PROJECT SUMMARY", "project_story": "PROJECT STORY", "source": "RÉSUMÉ TEXT (verbatim)",
           "story_slot": "CANDIDATE'S OWN WORDS", "fact": "FACT",
           "practice": "INDUSTRY PRACTICE (general knowledge, NOT the candidate's experience)", "jd": "JOB DESCRIPTION", "company": "COMPANY FACTS"}


def _render(chunks) -> str:
    blocks = []
    for c in chunks:
        label = _LABELS.get(c.kind, c.kind.upper()) + (f" · {c.project_id}" if c.project_id else "")
        blocks.append(f"[{label}]\n{c.text}")
    return "\n\n".join(blocks)


_HYPOTHETICAL = (
    "5. This question asks how you WOULD do something, or for an approach or evaluation method. Build the answer on the "
    "INDUSTRY PRACTICE material: state the concrete plan in first person ('I would store...', 'I would measure...'), "
    "specific and in the order a practitioner would do it. Then, in ONE sentence, anchor it with a real example from the "
    "candidate's own PROJECT material, naming the project, but only where it truly applies. Copy that example's facts "
    "from the PROJECT text almost word for word and add no detail of your own (no invented test sets, reviewers, numbers or methods). Never claim the candidate "
    "did something that appears only under INDUSTRY PRACTICE, and never name a project, product or system that is not "
    "written in the PROJECT material. If the question also asks what the candidate HAS done and "
    "the project material has a matching real example, lead with that example, then extend with the practice for the "
    "part the project does not cover, and say plainly which part is which. Never describe a project's own domain as if "
    "it were the situation asked about.\n")


def build_prompt(question, chunks, job, limit=None, avoid=(), hypothetical=False) -> str:
    company = (job.get("company") if isinstance(job, dict) else None) or "the company"
    title = (job.get("title") if isinstance(job, dict) else None) or "the role"
    size = f"Keep it under {limit} characters." if limit else "Answer in 4-8 sentences."
    avoid_line = f"Do not mention: {', '.join(avoid)}.\n" if avoid else ""
    return (
        "You are answering ONE free-text question on a job application, in the candidate's own voice, first person.\n\n"
        "STRICT RULES (truthfulness is mandatory):\n"
        "1. Use ONLY the material below. Never invent an achievement, tool, metric or company fact. Start with the "
        "answer itself: never restate or paraphrase the question in your first sentence.\n"
        "2. Projects are separate: describe each one on its own and never merge details of different projects.\n"
        "3. Company specifics only if they appear under COMPANY FACTS or JOB DESCRIPTION.\n"
        f"4. Be concrete and specific. {size}\n{_HYPOTHETICAL if hypothetical else ''}"
        "6. If the material does not actually contain what the question asks for (for example a change driven by user "
        "feedback, when no project says so), do NOT bend a project to fit: write the honest closest answer and set "
        "confidence below 40 so a human reviews it.\n"
        f"{avoid_line}\n"
        f"ROLE: {title} at {company}\nQUESTION: {question}\n\nMATERIAL:\n{_render(chunks)}\n\n"
        'Reply with ONLY a JSON object: {"answer": "<the answer text>", "confidence": <0-100, how sure you are this '
        'answers the question correctly from the material above>, "basis": "<one short line: what it rests on>"}'
    )


def draft(question, chunks, job, llm, limit=None, avoid=(), hypothetical=False) -> dict:
    prompt = build_prompt(question, chunks, job, limit, avoid, hypothetical)
    answer = confidence = basis = None
    try:
        raw = llm(prompt)
        if isinstance(raw, str) and raw.strip():
            answer, confidence, basis = _parse_reply(raw)
    except Exception:
        answer = confidence = basis = None
    # parsed: True if JSON was successfully parsed (confidence or basis extracted), False for prose/empty/error
    parsed = confidence is not None or basis is not None
    return {"answer": answer or None, "confidence": confidence, "basis": basis, "parsed": parsed, "prompt": prompt}
