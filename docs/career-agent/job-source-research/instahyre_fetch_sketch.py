"""Instahyre read-only fetch via logged-in Chrome (CDP). Verified 2026-09-25.
List : GET /api/v1/job_search?skills=<term>&offset=N  (20/page, public search over ALL jobs, relevance-ranked, no dates)
Detail: GET /job-<id>-x/ HTML (slug ignored) -> JSON-LD JobPosting: datePosted (YYYY-MM-DD), full description.
Requests are same-origin fetch() inside our own tab (no navigation). Never clicks Apply/Interested."""
import json, random, re, time, urllib.parse
from playwright.sync_api import sync_playwright

nap = lambda a=3, b=7: time.sleep(random.uniform(a, b))

def list_jobs(page, term, offset=0):
    q = urllib.parse.urlencode({"company_size": 0, "isLandingPage": "true", "job_type": 0,
                                "offset": offset, "skills": term})   # add jobLocations=Bangalore / years=N optionally
    s, t = page.evaluate("u=>fetch(u,{credentials:'include'}).then(async r=>[r.status,await r.text()])",
                         "/api/v1/job_search?" + q)
    if s != 200:
        raise RuntimeError(f"job_search {s}")          # stop, do not retry (safety rule)
    d = json.loads(t)
    return d["meta"]["total_count"], [dict(
        key=f"instahyre:{o['id']}", job_id=o["id"], title=o["title"], company=o["employer"]["company_name"],
        location=o["locations"], skills=o["keywords"], url=o["public_url"]) for o in d["objects"]]

def job_detail(page, job_id):
    s, h = page.evaluate("u=>fetch(u,{credentials:'include'}).then(async r=>[r.status,await r.text()])",
                         f"/job-{job_id}-x/")
    if s != 200:
        raise RuntimeError(f"detail {s}")
    m = re.search(r'"datePosted": "([^"]+)"', h)
    ld = re.search(r'<script type="application/ld\+json">\s*(\{"@context": "https://schema.org", "@type": "JobPosting".*?\})\s*</script>', h, re.S)
    jp = json.loads(ld.group(1)) if ld else {}
    return dict(date_posted=m.group(1) if m else None, description_html=jp.get("description"),
                apply_type="native")  # Apply now => submitChoice*() in-site 'interest'; no external URL anywhere

def main(terms=("machine learning engineer",), pages=1):
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp("http://localhost:9222")
    page = b.contexts[0].new_page()                     # own tab only
    try:
        page.goto("https://www.instahyre.com/search-jobs?skills=Machine%20Learning", wait_until="networkidle")
        if "/login" in page.url:                        # logged out => stop
            raise SystemExit("not logged in")
        for t in terms:
            for p in range(pages):
                nap(); total, jobs = list_jobs(page, t, 20 * p)
                print(t, p, total, len(jobs))
                for j in jobs[:2]:
                    nap(); print(j["key"], job_detail(page, j["job_id"])["date_posted"])
    finally:
        page.close(); b.close(); pw.stop()

if __name__ == "__main__":
    main()
