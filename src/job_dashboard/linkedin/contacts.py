"""Turn a hiring post's free text into actionable channels, and a post into a
``JobListing`` so the per-job pipeline (tailored résumé, company research,
cover letter, career_agent) works on it unchanged.

Pure regex for contacts; role/company use a single local-Ollama JSON call with
a regex fallback. Nothing here sends anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from job_dashboard.models import JobListing

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_URL = re.compile(r"(?:https?://|\b(?:lnkd\.in|forms\.gle|bit\.ly)/)[^\s<>\"')]+")
# Indian mobiles (+91 / 10 digits starting 6-9) and generic +CC numbers.
_PHONE = re.compile(r"(?:\+\d{1,3}[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b|\+\d{1,3}[\s-]?\d[\d\s-]{7,12}\d")
_DM = re.compile(r"\b(?:DM|dm me|direct message|inbox me|message me)\b", re.I)
_FORM_HOSTS = ("forms.gle/", "docs.google.com/forms", "forms.office.com", "typeform.com",
               "jotform.com", "tally.so")
_NOISE_LINK = ("linkedin.com/in/", "linkedin.com/feed", "linkedin.com/company")


def extract_contacts(text: str, url: str | None = None) -> dict:
    """{emails, forms, links, phones, dm} found in ``text`` (+ the post url when
    it is an embedded apply link rather than the poster's profile)."""
    text = text or ""
    raw = [u.rstrip(".,;:!") for u in _URL.findall(text)]
    if url and "linkedin.com/in/" not in url:
        raw.append(url)
    links = []
    for u in raw:
        u = u if u.startswith("http") else "https://" + u
        if u not in links and not any(n in u for n in _NOISE_LINK):
            links.append(u)
    forms = [u for u in links if any(h in u for h in _FORM_HOSTS)]
    return {
        "emails": list(dict.fromkeys(e.rstrip(".").lower() for e in _EMAIL.findall(text))),
        "forms": forms,
        "links": [u for u in links if u not in forms],
        "phones": list(dict.fromkeys(re.sub(r"[\s-]", "", p) for p in _PHONE.findall(text))),
        "dm": bool(_DM.search(text)),
    }


def resolve_link(url: str, get=None) -> str:
    """Follow a shortener (lnkd.in, forms.gle, bit.ly) to its final URL; the
    input url on any failure. LinkedIn's lnkd.in interstitial keeps the real
    target in the page, so fall back to scraping it from the body."""
    try:
        if get is None:
            import requests
            get = lambda u: requests.get(u, timeout=10, allow_redirects=True,  # noqa: E731
                                         headers={"User-Agent": "Mozilla/5.0"})
        r = get(url)
        final = str(r.url)
        if "lnkd.in" in final or "linkedin.com/safety" in final:
            m = re.search(r'href="(https?://(?!www\.linkedin|lnkd\.in)[^"]+)"', r.text or "")
            if m:
                final = m.group(1)
        return final
    except Exception:  # noqa: BLE001
        return url


def _regex_role(post: dict) -> dict:
    text = post.get("text") or ""
    head = post.get("poster_headline") or ""
    m = re.search(r"(?:Role|Position|Title|Opening)\s*[:\-–]\s*([^|📍🏢💼\n]{3,70}?)"
                  r"(?=\s*(?:Location|Experience|Company|📍|🏢|💼|\||$))", text, re.I)
    m = m or re.search(r"(?:hiring|looking for)\s+(?:an?\s+)?([A-Z][\w/&+ .-]{3,60}?)"
                       r"(?=\s*(?:\(|to join|in |at |\||–|-|!|\.|,))", text)
    title = m.group(1).strip(" :-–") if m else ""
    c = (re.search(r"Company\s*[:\-–]\s*([^|📍💼\n(]{2,50})", text, re.I)
         or re.search(r"\b(?:at|@)\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,3})", head))
    company = c.group(1).strip(" .,") if c else ""
    if not company:
        emails = extract_contacts(text)["emails"]
        dom = emails[0].split("@")[1].split(".")[0] if emails else ""
        if dom and dom not in ("gmail", "yahoo", "outlook", "hotmail"):
            company = dom.capitalize()
    loc = re.search(r"Locations?\s*[:\-–]?\s*([^|💼🕒\n]{2,50}?)(?=\s*(?:Experience|Work|Employ|💼|🕒|\||$))",
                    text, re.I)
    return {"title": title, "company": company, "location": loc.group(1).strip(" 📍|") if loc else ""}


def extract_role(post: dict, post_fn=None) -> dict:
    """{title, company, location} for a post: local Ollama first, regex fills gaps."""
    guess = _regex_role(post)
    try:
        if post_fn is None:
            from job_dashboard.resume.resume_llm import _default_post as post_fn
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        prompt = ("From this LinkedIn hiring post, return ONLY JSON "
                  '{"title": "...", "company": "...", "location": "..."} — the role being '
                  "hired for, the HIRING company (not a recruiting agency if the client is "
                  'named), and location. Use "" when not stated.\n\n'
                  f"Poster headline: {post.get('poster_headline') or ''}\n"
                  f"Post: {(post.get('text') or '')[:3000]}")
        resp = post_fn(f"{host}/api/generate", {
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"), "prompt": prompt,
            "stream": False, "format": "json", "options": {"temperature": 0.1}})
        got = json.loads(resp["response"])
        for k in guess:
            v = got.get(k)
            if isinstance(v, str) and v.strip():
                guess[k] = v.strip()
    except Exception:  # noqa: BLE001 — Ollama down → regex guess stands
        pass
    return guess


def apply_channel(contacts: dict, resolve=resolve_link) -> tuple[str | None, str]:
    """Best apply route, best-first: form > external link (resolved) > email >
    LinkedIn job page > dm. A recruiter's email beats LinkedIn Easy Apply."""
    if contacts["forms"]:
        return resolve(contacts["forms"][0]), "form"
    resolved = [resolve(u) for u in contacts["links"]]
    ext = [u for u in resolved if "linkedin.com" not in u]
    if ext:
        return ext[0], "external"
    if contacts["emails"]:
        return "mailto:" + contacts["emails"][0], "email"
    if resolved:
        return resolved[0], "external"
    return None, "dm"


def post_to_job(post: dict, role: dict, resolve=resolve_link) -> JobListing:
    contacts = extract_contacts(post.get("text"), post.get("url"))
    apply_url, kind = apply_channel(contacts, resolve)
    return JobListing(
        source="linkedin_post",
        title=role.get("title") or "Role from LinkedIn post",
        company=role.get("company") or post.get("poster_name") or "Unknown",
        location=role.get("location") or None,
        description=post.get("text") or "",
        job_url=post["url"],
        external_id=f"hiring_post:{post['id']}",
        apply_url=apply_url, apply_kind=kind,
    )


def text_key(text: str) -> str:
    """Near-duplicate key: same post reshared/re-fetched → same key."""
    norm = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return hashlib.sha1(norm[:400].encode()).hexdigest()
