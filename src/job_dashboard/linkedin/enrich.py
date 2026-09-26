"""Fill in what a requirements-only hiring post leaves out by reading the
company's own pages: links in the post, the company site, and the careers page
or listing for this role found by search.

Reuses ``letter.company_research``'s TinyFish search/fetch adapters; the local
Ollama model reads the fetched pages and returns ONLY what they state. Never
raises: any failure yields an empty result and the post text stands alone.
"""
from __future__ import annotations

import json
import os

_MAX_PAGES = 4
_PAGE_CHARS = 5000
_FREE_MAIL = ("gmail", "yahoo", "outlook", "hotmail", "icloud", "proton")

_PROMPT = """You are given a LinkedIn hiring post and pages fetched from the web.
Using ONLY facts stated in the pages (never invent), return JSON:
{{"company_about": "2-3 sentences: what the company does, product, size/stage if stated",
  "role_details": "responsibilities, requirements, experience, compensation, work mode for THIS role if a page describes it; else empty",
  "apply_url": "the page URL where this specific role can be applied to, else empty",
  "website": "the company's own website, else empty"}}
Use "" for anything the pages do not state. Only use a page that is about {company}.

Role: {title} at {company}
Post: {post}

Pages:
{pages}"""


def _candidate_urls(contacts: dict, role: dict, search) -> list[str]:
    urls = list(contacts.get("forms", [])) + list(contacts.get("links", []))
    for e in contacts.get("emails", []):
        dom = e.split("@")[1]
        if dom.split(".")[0] not in _FREE_MAIL:
            urls.append(f"https://{dom}")
    company, title = role.get("company"), role.get("title")
    if company:
        for q in (f'{company} careers {title or ""}'.strip(), f"{company} company about"):
            try:
                urls += [r.get("url") for r in (search(q) or [])[:3] if r.get("url")]
            except Exception:  # noqa: BLE001
                continue
    return list(dict.fromkeys(u for u in urls if u))[:_MAX_PAGES + 2]


def _ollama(prompt: str, post_fn) -> dict:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    resp = post_fn(f"{host}/api/generate", {
        "model": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"), "prompt": prompt,
        "stream": False, "format": "json", "options": {"temperature": 0.1, "num_ctx": 16384}})
    return json.loads(resp["response"])


def research_role(post: dict, role: dict, contacts: dict, *, search=None, fetch=None,
                  post_fn=None) -> dict:
    """{company_about, role_details, apply_url, website, sources} — "" when unknown."""
    empty = {"company_about": "", "role_details": "", "apply_url": "", "website": "", "sources": []}
    try:
        from job_dashboard.letter.company_research import _default_fetch, _default_search
        from job_dashboard.resume.resume_llm import _default_post
        search, fetch, post_fn = search or _default_search, fetch or _default_fetch, post_fn or _default_post
        urls = _candidate_urls(contacts, role, search)
        if not urls:
            return empty
        pages = []
        for item in fetch(urls) or []:
            text = item.get("text") or item.get("content") or item.get("markdown") or ""
            url = item.get("url") or item.get("final_url")
            if url and len(text) > 200:
                pages.append((url, text[:_PAGE_CHARS]))
            if len(pages) >= _MAX_PAGES:
                break
        if not pages:
            return empty
        got = _ollama(_PROMPT.format(
            company=role.get("company") or "the hiring company", title=role.get("title") or "",
            post=(post.get("text") or "")[:2500],
            pages="\n\n".join(f"[{u}]\n{t}" for u, t in pages)), post_fn)
        out = {k: str(got.get(k) or "").strip() for k in empty if k != "sources"}
        out["sources"] = [u for u, _ in pages]
        return out
    except Exception:  # noqa: BLE001
        return empty


def enriched_description(post_text: str, info: dict) -> str:
    """Post text + what the company's pages add, so résumé tailoring and the
    cover letter see the full picture."""
    parts = [post_text]
    if info.get("role_details"):
        parts.append(f"Role details (from company pages):\n{info['role_details']}")
    if info.get("company_about"):
        parts.append(f"About the company:\n{info['company_about']}")
    if info.get("sources"):
        parts.append("Sources: " + ", ".join(info["sources"]))
    return "\n\n".join(parts)
