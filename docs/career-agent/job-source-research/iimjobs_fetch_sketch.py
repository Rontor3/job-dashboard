"""IIMJobs list+detail fetch via the logged-in CDP Chrome (read-only). Verified 2026-09-25.
List : GET https://gladiator.iimjobs.com/job/search?query=<text>&page=<n>&posting=<days>   (header version: 2)
Detail: GET https://gladiator.iimjobs.com/job/detail?jobcode=<id>   -> data.introText = HTML description
Called with fetch() from inside an iimjobs.com tab so the session cookie is used. Nothing is clicked.
"""
import json, random, time, urllib.parse
from playwright.sync_api import sync_playwright

API = "https://gladiator.iimjobs.com/job"
_JS = """async (u)=>{const r=await fetch(u,{credentials:'include',headers:{version:'2'}});
 return [r.status, await r.text()]}"""

def canonical_key(job) -> str:
    return f"iimjobs:{job['id']}"          # numeric id, also last '-<id>' of /j/<slug>-<id>

def canonical_url(job) -> str:
    return job.get("jobDetailUrl") or f"https://www.iimjobs.com/j/x-{job['id']}"  # slug is cosmetic

def apply_type(job) -> tuple[str, str | None]:
    # applyStatus 1 + applyUrl "" -> native in-site apply ; applyStatus 2 + applyUrl -> external (URL readable, no click)
    return ("external", job["applyUrl"]) if job.get("applyUrl") else ("native", None)

def posted_hours(job, now_ms=None):
    return ((now_ms or time.time() * 1000) - job["createdTimeMs"]) / 3.6e6   # createdTimeMs = precise epoch ms

def _get(page, url):
    st, txt = page.evaluate(_JS, url)
    time.sleep(random.uniform(3, 6))
    if st != 200:
        raise RuntimeError(f"HTTP {st} {url} {txt[:120]}")   # stop on ANY non-200 (403/429 = throttling/challenge)
    return json.loads(txt)

def search(page, term, posting=7, max_pages=5):
    """Yield deduped jobs for a term. Pages overlap (relevance order) so dedupe by id."""
    seen = set()
    for pg in range(max_pages):
        j = _get(page, f"{API}/search?query={urllib.parse.quote(term)}&page={pg}&posting={posting}")
        for x in j["data"]:
            if x["id"] not in seen:
                seen.add(x["id"]); yield x
        if not j.get("hasMore"):
            break

def detail(page, job_id):
    return _get(page, f"{API}/detail?jobcode={job_id}")["data"]   # ["introText"] = full JD html

def open_tab(cdp="http://localhost:9222"):
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp)
    page = browser.contexts[0].new_page()                # own tab
    page.goto("https://www.iimjobs.com/k/data-scientist-jobs", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)                           # gives same-origin + cookies
    return pw, browser, page

if __name__ == "__main__":
    pw, browser, page = open_tab()
    try:
        for j in list(search(page, "llm engineer", posting=7))[:3]:
            kind, url = apply_type(j)
            d = detail(page, j["id"])
            print(canonical_key(j), j["title"], round(posted_hours(j), 1), kind, url and url[:60], len(d["introText"] or ""))
    finally:
        page.close(); browser.close(); pw.stop()
