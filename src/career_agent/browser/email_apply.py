"""A posting whose Apply is an email link (mailto:) is applied to by email, not by any form on the page.

Live Aezion 2026-10-19: "Apply for job" -> mailto:tag@aezion.com, and the agent filled the site's other form
instead. Here the application becomes a Gmail DRAFT to that address with the candidate's own résumé attached (the
same Rakshit_Singh_Resume.pdf every application uses); the human reads it and sends it. Never sends.
"""
from __future__ import annotations

import re

_APPLY_TEXT = re.compile(r"\bapply\b|send (your )?(cv|resume|résumé)|email (your )?(cv|resume|résumé)", re.I)

_MAILTO_JS = """(re) => {
  const rx = new RegExp(re, 'i');
  const out = [];
  for (const a of document.querySelectorAll('a[href^="mailto:"]')) {
    const r = a.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const t = (a.innerText || a.getAttribute('aria-label') || '').trim();
    if (rx.test(t)) out.push({text: t.slice(0, 60), href: a.getAttribute('href')});
  }
  return out;
}"""


def mailto_apply(page) -> dict | None:
    """{'to', 'subject'} when the page's Apply is an email link, else None."""
    try:
        hits = page.evaluate(_MAILTO_JS, _APPLY_TEXT.pattern)
    except Exception:
        return None
    for h in hits or []:
        m = re.match(r"mailto:([^?]+)(?:\?(.*))?", h.get("href") or "", re.I)
        if not m or "@" not in m.group(1):
            continue
        q = dict(p.split("=", 1) for p in (m.group(2) or "").split("&") if "=" in p)
        from urllib.parse import unquote
        return {"to": unquote(m.group(1)).strip(), "subject": unquote(q.get("subject", "")).strip()}
    return None


def draft_application(to: str, subject: str, title: str, company: str, contact: dict, resume_pdf) -> dict:
    """Create the Gmail draft. Returns {'drafted': bool, 'gmail_url'|'problem': ...}."""
    from pathlib import Path
    from job_dashboard.apply import gmail_draft
    name = contact.get("full_name") or ""
    role = f"the {title} role" if title else "the opening"
    at = f" at {company}" if company else ""
    body = (f"Hi,\n\nI'd like to apply for {role}{at}. I'm a Data Scientist at Tata AIG working on ML fraud-detection "
            f"systems and LLM pipelines; my résumé is attached.\n\nHappy to share more or set up a quick call.\n\n"
            f"Best,\n{name}\n{contact.get('phone') or ''}\n{contact.get('linkedin_url') or contact.get('linkedin') or ''}")
    subject = subject or (f"Application: {title}" if title else "Job application")
    pdf = Path(resume_pdf) if resume_pdf else None
    if not gmail_draft.authorized() or not pdf or not pdf.exists():
        return {"drafted": False, "problem": "Gmail drafting not connected or no résumé file"}
    try:
        d = gmail_draft.create_draft(gmail_draft.compose_message(to, subject, body, pdf, filename=pdf.name))
        return {"drafted": True, "gmail_url": gmail_draft.draft_url(d["message_id"], contact.get("email") or "")}
    except Exception as e:  # noqa: BLE001
        return {"drafted": False, "problem": f"{type(e).__name__}"}
