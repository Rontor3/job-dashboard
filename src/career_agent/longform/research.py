"""What a company builds and is known for, for 'why us' / 'what interests you' answers and notes to a team.

Sources, best first: the resources you picked on the dashboard; the job description's own words about the company;
stored research that is really about the company; else a fresh lookup — TinyFish search when TINYFISH_API_KEY is set,
then Claude Haiku's web search (pointed at the company's own site) whenever the search gave fewer than two facts about
the company. Only the company name, job title and site leave the machine.

A fact counts only when it is ABOUT this company: from its own site, or naming it, and never a social post or a job
board (Triosoft's four "facts" were Gauss Algorithmic's and Infosys's case-study pages and a Women's Day post,
2026-10-26). Stored research that fails that check is replaced, not reused forever. Never raises: no research is an
empty bundle."""
from __future__ import annotations

from ..orchestrator.claude_assist import first_json
import re
import subprocess
import tempfile
from urllib.parse import urlparse

from job_dashboard.artifacts_store import (_ensure_company_resources_table, company_key, company_resources_for,
                                           selected_resources_for, upsert_company_resources)
from job_dashboard.letter.company_research import Fact, ResearchBundle

_EMPTY = ResearchBundle(facts=[], queries_used=[], empty=True)
_PROMPT = ("Research the company \"{company}\" (hiring for: {title}).{site} Use web search and the company's own site. "
           "Find 3-5 specific, verifiable facts a candidate could mention: what they build and for whom, notable "
           "products or technical work, recent launches, funding or customers. Every fact must be about {company} "
           "itself, not another company and not a social-media post. Skip generic praise.\n"
           'Reply with ONLY JSON: {{"facts": [{{"text": "one sentence", "url": "source url"}}]}}')
MIN_FACTS = 2

# Never a source of facts about the company: social posts and job boards / application systems.
_NOT_A_SOURCE = ("linkedin.", "instagram.", "facebook.", "twitter.", "x.com", "youtube.", "tiktok.", "threads.",
                 "glassdoor.", "ambitionbox.", "naukri.", "indeed.", "wellfound.", "iimjobs.", "foundit.", "monster",
                 "instahyre.", "himalayas.", "workatastartup.", "ycombinator.com/companies")
_ATS = ("myworkdayjobs.", "greenhouse.", "lever.co", "smartrecruiters.", "successfactors.", "icims.", "taleo.",
        "zohorecruit.", "keka.", "darwinbox.", "oraclecloud.", "ashbyhq.", "workable.", "bamboohr.", "recruitee.",
        "jobvite.", "peoplestrong.", "freshteam.", "breezy.hr")
_LEGAL = {"pvt", "private", "ltd", "limited", "inc", "llc", "llp", "corp", "corporation", "co", "plc", "gmbh",
          "technologies", "technology", "tech", "solutions", "services", "systems", "software", "consulting",
          "india", "group", "global", "labs", "the", "and", "of"}


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")


def _name_tokens(company: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (company or "").lower()) if w not in _LEGAL and len(w) >= 3]


def company_site(job: dict) -> str:
    """The company's own site, from the job's apply/job link when that is not a job board or an application system."""
    for url in ((job or {}).get("apply_url"), (job or {}).get("job_url")):
        h = _host(url or "")
        if h and not any(b in h for b in _NOT_A_SOURCE + _ATS) and not h.startswith(("ad.", "click.")):
            return f"https://{h}"
    return ""


def about_company(text: str, url: str, company: str, site: str = "") -> bool:
    """The fact is about THIS company: from its own site, or naming it — never a social post or job board."""
    h = _host(url)
    if not h or any(b in h for b in _NOT_A_SOURCE):
        return False
    toks = _name_tokens(company)
    if (site and h == _host(site)) or any(t in h.replace("-", "") for t in toks if len(t) >= 4):
        return True                                    # the company's own domain
    low = (text or "").lower()
    return bool(toks) and all(t in low for t in toks)  # a third-party page counts only when it names the company


_JD_SKIP = re.compile(r"\b(you will|you'll|must|required|requirement|experience (in|with)|years|skills?|qualif|"
                      r"responsib|candidate|apply|salary|lpa|ctc|benefits?)\b", re.I)


def jd_facts(job: dict, company: str) -> list[dict]:
    """The job description's own sentences about what the company builds ('We are … building AI Voice Agents …')."""
    desc = re.sub(r"\s+", " ", (job or {}).get("description") or "")
    toks = _name_tokens(company)
    out = []
    for s in re.split(r"(?<=[.!?])\s+", desc):
        s = s.strip()
        words = s.split()
        if not (8 <= len(words) <= 60):
            continue
        url = (job or {}).get("job_url") or (job or {}).get("apply_url") or ""
        talks = re.match(r"(we|our|at)\b", s, re.I) or any(t in s.lower() for t in toks)
        # "We are looking for an ML engineer … to build intelligent AI Voice Agents and Chatbot solutions": the hiring
        # sentence still says what the company builds — keep that part
        aim = re.search(r"\bto (build|develop|create|design|scale|power)\b(.+)", s, re.I)
        if talks and aim and _JD_SKIP.search(s[:aim.start()]):
            out.append({"text": f"{company} is hiring to {aim.group(1).lower()}{aim.group(2).rstrip('.')}."[:400], "url": url})
        elif talks and re.search(r"\b(build|building|develop|product|platform|solution|customers?|clients?|serv(e|ing)|"
                                 r"mission|founded|leader|provid)", s, re.I) and not _JD_SKIP.search(s.split(" to ")[0]):
            out.append({"text": s[:400], "url": url})
        if len(out) == 3:
            break
    if not out:
        # job boards run the description together without full stops: find the hiring line in the whole text
        m = re.search(r"\b(?:we|our team)\b[^.]{0,200}?\bto (build|develop|create|design|scale|power)\b([^.]{10,200})", desc, re.I)
        if m:
            out.append({"text": f"{company} is hiring to {m.group(1).lower()}{m.group(2).rstrip()}."[:400],
                        "url": (job or {}).get("job_url") or (job or {}).get("apply_url") or ""})
    return out


def haiku_lookup(company: str, title: str, timeout: int = 180, site: str = "") -> list[dict]:
    """[{text, url}] from a Claude Haiku web lookup; [] on any failure."""
    try:
        r = subprocess.run(["claude", "-p", "--model", "haiku", "--allowedTools", "WebSearch,WebFetch",
                            "--tools", "WebSearch,WebFetch"],
                           input=_PROMPT.format(company=company, title=title or "a role",
                                                site=f" Their own website is {site} — start there." if site else ""),
                           capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir())
        raw = r.stdout or ""
        data = first_json(raw)
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


def tinyfish_then_haiku(company: str, title: str, description: str = "", site: str = "") -> list[dict]:
    """TinyFish search (needs TINYFISH_API_KEY), then the Haiku lookup when the search gave fewer than MIN_FACTS facts
    about the company — junk search results no longer stand in for research."""
    import os
    good = []
    if os.getenv("TINYFISH_API_KEY"):
        from job_dashboard.letter.company_research import company_research
        b = company_research(company, title, description)
        good = [{"text": f.text, "url": f.source_url} for f in b.facts if about_company(f.text, f.source_url, company, site)]
    if len(good) < MIN_FACTS:
        seen = {g["url"] for g in good}
        good += [f for f in haiku_lookup(company, title, site=site)
                 if about_company(f["text"], f["url"], company, site) and f["url"] not in seen]
    return good[:5]


def research_for(conn, job: dict, lookup=None) -> ResearchBundle:
    company = (job or {}).get("company") or ""
    ck = company_key(company)
    if not ck:
        return _EMPTY
    if conn is not None and (job or {}).get("id") and not ((job or {}).get("apply_url") or (job or {}).get("job_url")):
        try:                                                  # the caller's job row may not carry its links
            r = conn.execute("SELECT apply_url, job_url FROM jobs WHERE id = ?", (job["id"],)).fetchone()
            if r:
                job = {**job, "apply_url": r[0], "job_url": r[1]}
        except Exception:
            pass
    site = company_site(job)
    from_jd = jd_facts(job, company)
    try:
        _ensure_company_resources_table(conn)
        rows = selected_resources_for(conn, ck)              # what you picked on the dashboard stands as it is
        if not rows:
            stored = company_resources_for(conn, ck)
            rows = [r for r in stored if about_company(r["summary"] or "", r["source_url"], company, site)]
            # look again when nothing stored is about the company, or junk had to be dropped and too little is left
            if not rows or (len(rows) < len(stored) and len(rows) < MIN_FACTS):
                title = (job or {}).get("title") or ""
                found = (lookup(company, title) if lookup else
                         tinyfish_then_haiku(company, title, (job or {}).get("description") or "", site))
                found = [f for f in found if about_company(f["text"], f["url"], company, site)]
                bad = [r["source_url"] for r in stored if r not in rows]
                if bad:                                       # stored research that is not about the company: replaced
                    conn.executemany("DELETE FROM company_resources WHERE company_key = ? AND source_url = ? AND selected = 0",
                                     [(ck, u) for u in bad])
                if found:
                    upsert_company_resources(conn, ck, [{"source_url": f["url"], "title": company, "summary": f["text"]}
                                                        for f in found])
                conn.commit()
                rows = [r for r in company_resources_for(conn, ck)
                        if about_company(r["summary"] or "", r["source_url"], company, site)]
    except Exception:
        rows = []
    facts = [Fact(text=f["text"], source_url=f["url"]) for f in from_jd]
    facts += [Fact(text=r["summary"], source_url=r["source_url"]) for r in rows if r["summary"]]
    return ResearchBundle(facts=facts, queries_used=[], empty=not facts)
