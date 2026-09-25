"""Naukri list+detail fetch over the logged-in CDP Chrome. READ-ONLY. Verified 2026-09-25.
List  : replay the site's own jobapi/v3/search from inside a naukri.com tab using the headers the page itself
        sent (Bearer/nkparam/appid...) -> JSON with createdDate(ms), companyApplyJob, applyRedirectUrl.
        WARNING: after ~16 replayed calls (~2.5 min at 3-7s pacing) the API answered 406 'recaptcha required'.
        Treat 406 as a hard stop. Unverified safer variant: trigger the call by real UI nav (click page 2 / sort).
Detail: page.goto(job url) -> SSR HTML; full JD in <script type=application/ld+json> JobPosting (1 page load/job).
        (jobapi/v4/job/<id> direct fetch => 406 'recaptcha required' -- do not use.)
Never touches Apply; never opens applyRedirectUrl / companyApplyUrl.
"""
import json, re, time, random, urllib.parse
from playwright.sync_api import sync_playwright

nap = lambda a=3, b=7: time.sleep(random.uniform(a, b))
KEEP = ('appid', 'authorization', 'systemid', 'clientid', 'nkparam', 'gid', 'accept', 'content-type')
class Blocked(Exception): pass

def open_session(cdp="http://localhost:9222"):
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp)
    page = browser.contexts[0].new_page()                       # own tab
    reqs = []
    page.on("request", lambda r: reqs.append(dict(r.headers)) if "/jobapi/v3/search" in r.url else None)
    page.goto("https://www.naukri.com/data-scientist-jobs-in-india", wait_until="domcontentloaded")
    time.sleep(4)                                               # SSR page: no API call yet
    page.click("#filter-sort"); time.sleep(1)                   # UI sort menu (not Apply) -> makes page call the API
    page.click("[data-filter-id=sort] li:has-text('Date')"); time.sleep(4)
    if not reqs: raise Blocked("page did not issue jobapi/v3/search")
    hdr = {k: v for k, v in reqs[-1].items() if k in KEEP}      # keep in memory only, never persist (bearer = PII)
    return pw, browser, page, hdr

_JS = "async ([u,h])=>{const r=await fetch(u,{headers:h,credentials:'include'});return {s:r.status,t:await r.text()}}"

def search(page, hdr, keyword, page_no=1, location="india", job_age=None, sort=None):
    """job_age in {1,3,7,15,30} (calendar days); sort in {None(relevance-ish default),'f'(newest, noisy)}."""
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    q = dict(noOfResults=20, urlType="search_by_key_loc", searchType="adv", location=location, keyword=keyword,
             pageNo=page_no, seoKey=f"{slug}-jobs-in-{location}", src="jobsearchDesk")
    if sort: q["sort"] = sort
    if job_age: q["jobAge"] = job_age
    url = "https://www.naukri.com/jobapi/v3/search?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
    r = page.evaluate(_JS, [url, hdr])
    if r["s"] != 200: raise Blocked(f"HTTP {r['s']}: {r['t'][:120]}")      # 406 recaptcha => STOP, don't retry
    return json.loads(r["t"])

def canonical_key(d): return "naukri:" + str(d["jobId"])
def canonical_url(d): return "https://www.naukri.com" + d["jdURL"]          # already tracking-free

def to_record(d, now_ms=None):
    now_ms = now_ms or time.time() * 1000
    external = bool(d.get("companyApplyJob"))
    return dict(key=canonical_key(d), url=canonical_url(d), title=d["title"], company=d["companyName"],
                posted_ms=d["createdDate"], posted_raw=d["footerPlaceholderLabel"],
                posted_hours=round((now_ms - d["createdDate"]) / 3.6e6, 1),
                apply_type="external" if external else "native",
                external_url=d.get("applyRedirectUrl") if external else None,   # employer/ATS URL, read from JSON only
                has_screening_questions=bool(d.get("questionnaireIdPresent")),
                skills=d.get("tagsAndSkills"), jd_snippet=d.get("jobDescription", ""),  # snippet ~0.9k chars, NOT full JD
                experience=next((p["label"] for p in d.get("placeholders", []) if p["type"] == "experience"), None),
                location=next((p["label"] for p in d.get("placeholders", []) if p["type"] == "location"), None))

def detail(page, url):
    """1 page load. Full JD from JSON-LD; button text distinguishes 'Apply' vs 'Apply on company site'."""
    page.goto(url, wait_until="domcontentloaded"); time.sleep(4)
    ld = page.evaluate("""()=>{for(const s of document.querySelectorAll('script[type="application/ld+json"]')){
        try{const j=JSON.parse(s.textContent); if(j['@type']=='JobPosting') return j}catch(e){}} return null}""")
    btn = page.evaluate("[...document.querySelectorAll('button')].map(b=>b.innerText.trim()).filter(t=>/^apply/i.test(t))[0]||null")
    return dict(jsonld=ld, apply_button=btn)

if __name__ == "__main__":
    pw, br, page, hdr = open_session()
    try:
        for pg in (1,):
            nap(); j = search(page, hdr, "machine learning engineer", pg, job_age=3)
            print("total", j["noOfJobs"])
            for d in j["jobDetails"][:5]: print(to_record(d))
    finally:
        page.close(); br.close(); pw.stop()
