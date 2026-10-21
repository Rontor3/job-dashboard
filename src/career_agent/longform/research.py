"""What a company builds and is known for, for 'why us' / 'what interests you' answers and notes to a team.

Order: the resources you picked on the dashboard, then any stored for the company, then a one-time lookup: TinyFish
search when TINYFISH_API_KEY is set (as the letter screen does), else Claude Haiku's web search through the logged-in
Claude CLI (only the company name and job title leave the machine). A lookup's
findings are stored in company_resources, so each company is researched once and the dashboard's letter screen sees
them too. Never raises: no research is an empty bundle."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile

from job_dashboard.artifacts_store import (_ensure_company_resources_table, company_key, company_resources_for,
                                           selected_resources_for, upsert_company_resources)
from job_dashboard.letter.company_research import Fact, ResearchBundle

_EMPTY = ResearchBundle(facts=[], queries_used=[], empty=True)
_PROMPT = ("Research the company \"{company}\" (hiring for: {title}). Use web search and the company's own site. "
           "Find 3-5 specific, verifiable facts a candidate could mention: what they build and for whom, notable "
           "products or technical work, recent launches, funding or customers. Skip generic praise.\n"
           'Reply with ONLY JSON: {{"facts": [{{"text": "one sentence", "url": "source url"}}]}}')


def haiku_lookup(company: str, title: str, timeout: int = 180) -> list[dict]:
    """[{text, url}] from a Claude Haiku web lookup; [] on any failure."""
    try:
        r = subprocess.run(["claude", "-p", "--model", "haiku", "--allowedTools", "WebSearch,WebFetch",
                            "--tools", "WebSearch,WebFetch"],
                           input=_PROMPT.format(company=company, title=title or "a role"),
                           capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir())
        raw = r.stdout or ""
        i = raw.find("{")
        data = json.JSONDecoder().raw_decode(raw[i:])[0] if i >= 0 else {}
    except (BrokenPipeError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        m = {BrokenPipeError: "epipe", subprocess.TimeoutExpired: "timeout", FileNotFoundError: "cli_missing"}
        print(f"[assist] company research unavailable ({next((v for k, v in m.items() if isinstance(e, k)), 'os_error')})",
              flush=True)
        return []
    except Exception:
        return []
    out = []
    for f in (data.get("facts") or []) if isinstance(data, dict) else []:
        text, url = str((f or {}).get("text") or "").strip(), str((f or {}).get("url") or "").strip()
        if text and re.match(r"https?://", url):
            out.append({"text": text[:400], "url": url})
    return out[:5]


def tinyfish_then_haiku(company: str, title: str, description: str = "") -> list[dict]:
    """TinyFish search (the dashboard's letter research; needs TINYFISH_API_KEY), else the Haiku web lookup."""
    import os
    if os.getenv("TINYFISH_API_KEY"):
        from job_dashboard.letter.company_research import company_research
        b = company_research(company, title, description)
        if b.facts:
            return [{"text": f.text, "url": f.source_url} for f in b.facts[:5]]
    return haiku_lookup(company, title)


def research_for(conn, job: dict, lookup=None) -> ResearchBundle:
    company = (job or {}).get("company") or ""
    ck = company_key(company)
    if not ck:
        return _EMPTY
    try:
        _ensure_company_resources_table(conn)
        rows = selected_resources_for(conn, ck) or company_resources_for(conn, ck)
        if not rows:
            found = (lookup(company, (job or {}).get("title") or "") if lookup else
                     tinyfish_then_haiku(company, (job or {}).get("title") or "", (job or {}).get("description") or ""))
            if found:
                upsert_company_resources(conn, ck, [{"source_url": f["url"], "title": company, "summary": f["text"]}
                                                    for f in found])
                rows = company_resources_for(conn, ck)
    except Exception:
        return _EMPTY
    facts = [Fact(text=r["summary"], source_url=r["source_url"]) for r in rows if r["summary"]]
    return ResearchBundle(facts=facts, queries_used=[], empty=not facts)
