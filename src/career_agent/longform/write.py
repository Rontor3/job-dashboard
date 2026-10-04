"""Writer: one model call that sees ONLY the retrieved chunks. Projects that were not retrieved are not in the
prompt, so they cannot be blended into the answer."""
from __future__ import annotations

from job_dashboard.apply.screening import _parse_reply

_LABELS = {"card": "PROJECT SUMMARY", "project_story": "PROJECT STORY", "source": "RÉSUMÉ TEXT (verbatim)",
           "story_slot": "CANDIDATE'S OWN WORDS", "fact": "FACT", "jd": "JOB DESCRIPTION", "company": "COMPANY FACTS"}


def _render(chunks) -> str:
    blocks = []
    for c in chunks:
        label = _LABELS.get(c.kind, c.kind.upper()) + (f" · {c.project_id}" if c.project_id else "")
        blocks.append(f"[{label}]\n{c.text}")
    return "\n\n".join(blocks)


def build_prompt(question, chunks, job, limit=None, avoid=()) -> str:
    company = (job.get("company") if isinstance(job, dict) else None) or "the company"
    title = (job.get("title") if isinstance(job, dict) else None) or "the role"
    size = f"Keep it under {limit} characters." if limit else "Answer in 4-8 sentences."
    avoid_line = f"Do not mention: {', '.join(avoid)}.\n" if avoid else ""
    return (
        "You are answering ONE free-text question on a job application, in the candidate's own voice, first person.\n\n"
        "STRICT RULES (truthfulness is mandatory):\n"
        "1. Use ONLY the material below. Never invent an achievement, tool, metric or company fact.\n"
        "2. Projects are separate: describe each one on its own and never merge details of different projects.\n"
        "3. Company specifics only if they appear under COMPANY FACTS or JOB DESCRIPTION.\n"
        f"4. Be concrete and specific. {size}\n{avoid_line}\n"
        f"ROLE: {title} at {company}\nQUESTION: {question}\n\nMATERIAL:\n{_render(chunks)}\n\n"
        'Reply with ONLY a JSON object: {"answer": "<the answer text>", "confidence": <0-100, how sure you are this '
        'answers the question correctly from the material above>, "basis": "<one short line: what it rests on>"}'
    )


def draft(question, chunks, job, llm, limit=None, avoid=()) -> dict:
    prompt = build_prompt(question, chunks, job, limit, avoid)
    answer = confidence = basis = None
    try:
        raw = llm(prompt)
        if isinstance(raw, str) and raw.strip():
            answer, confidence, basis = _parse_reply(raw)
    except Exception:
        answer = confidence = basis = None
    return {"answer": answer or None, "confidence": confidence, "basis": basis, "prompt": prompt}
