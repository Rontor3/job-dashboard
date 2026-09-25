"""Wellfound: public role pages, NO login needed. Data is server-rendered in #__NEXT_DATA__ (Apollo cache).
Run: python3 fetch_sketch.py   (attaches to CDP Chrome on :9222, own tab, read-only, 3-7s pacing)"""
import json, random, time
from playwright.sync_api import sync_playwright

ROLES = ["machine-learning-engineer", "ai-engineer", "data-scientist", "data-science",
         "artificial-intelligence-engineer", "machine-learning-scientist"]  # only slugs that resolve (else -> /location/india)
nap = lambda a=3, b=7: time.sleep(random.uniform(a, b))

def parse_listing(pp):
    """pageProps -> (meta, jobs). Jobs = each startup's highlightedJobListings (desc included, full text)."""
    st = pp["apolloState"]["data"]; out = []; meta = {}
    for k, v in st["ROOT_QUERY"]["talent"].items():
        if not k.startswith("seoLandingPageJobSearchResults"): continue
        meta = {x: v[x] for x in ("totalStartupCount", "totalJobCount", "perPage", "pageCount")}
        for s in v["startups"]:
            su = st[s["__ref"]]
            for j in su.get("highlightedJobListings", []):
                jl = st[j["__ref"]]
                out.append(dict(
                    id=jl["id"], slug=jl["slug"], title=jl["title"], company=su["name"], company_slug=su["slug"],
                    url=f"https://wellfound.com/jobs/{jl['id']}-{jl['slug']}",
                    posted_ts=jl.get("liveStartAt"),           # unix secs, == JSON-LD datePosted; bumps on repost
                    ats_source=jl.get("atsSource"),            # Greenhouse/Ashby/Workable-synced (still directApply)
                    auto_posted=jl.get("autoPosted"),          # True => JSON-LD directApply=false (external/scraped)
                    locations=jl.get("locationNames"), remote=(jl.get("remoteConfig") or {}).get("kind"),
                    comp=jl.get("compensation"), years_min=jl.get("yearsExperienceMin"),
                    description=jl.get("description")))        # markdown, full JD
    return meta, out

def crawl_role(page, role, max_pages=None):
    seen = {}
    pg = 1
    while True:
        url = f"https://wellfound.com/role/l/{role}/india" + (f"?page={pg}" if pg > 1 else "")
        r = page.goto(url, wait_until="domcontentloaded"); nap()
        if r.status != 200 or "/role/" not in page.url:
            print("bad/redirect", url, r.status, page.url); break      # unknown role slug redirects to /location/india
        body = page.inner_text("body")[:1500].lower()
        if any(x in body for x in ("captcha", "verify you are", "unusual activity", "access denied")):
            print("CHALLENGE - stop"); break
        meta, jobs = parse_listing(json.loads(page.eval_on_selector("#__NEXT_DATA__", "e=>e.textContent"))["props"]["pageProps"])
        for j in jobs: seen[j["id"]] = j                                # same job can repeat across pages -> dedupe on id
        if pg >= meta["pageCount"] or (max_pages and pg >= max_pages): break
        pg += 1
    return seen

if __name__ == "__main__":
    pw = sync_playwright().start(); b = pw.chromium.connect_over_cdp("http://localhost:9222")
    page = b.contexts[0].new_page()
    try:
        jobs = crawl_role(page, "data-scientist")
        now = time.time()
        for j in sorted(jobs.values(), key=lambda j: -(j["posted_ts"] or 0))[:10]:   # list is NOT date-sorted -> sort client-side
            print(j["id"], round((now - j["posted_ts"]) / 86400, 1), "d", j["title"], "|", j["company"], "| auto" if j["auto_posted"] else "")
    finally:
        page.close(); b.close(); pw.stop()
