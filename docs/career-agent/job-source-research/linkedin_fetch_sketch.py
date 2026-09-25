"""LinkedIn Jobs fetcher sketch: read-only, via the logged-in Chrome over CDP.

One search page load makes LinkedIn's own SPA call (a) voyagerJobsDashJobCards twice
(start=0 and start=25, 25 cards each) and (b) a graphql 'jobPostingDetailDescription'
prefetch that carries the FULL description + apply info for the first ~25 cards.
We only listen to those responses; no clicks, no extra requests.

Run:  python3 fetch_sketch.py "machine learning engineer" [--hours 24] [--start 0]
"""
import json, random, re, sys, time
from playwright.sync_api import sync_playwright

BASE = "https://www.linkedin.com/jobs/search/"
TPR = {24: "r86400", 168: "r604800", 720: "r2592000"}
BAD_URL = re.compile(r"authwall|/login|/checkpoint|/uas/|challenge|captcha", re.I)
BAD_TEXT = re.compile(r"unusual activity|verify you.re a human|security verification|"
                      r"let.s do a quick security check|temporarily restricted", re.I)


class Checkpoint(Exception):
    pass


def search_url(term, hours=None, sort="DD", start=0, location="India"):
    from urllib.parse import quote
    u = f"{BASE}?keywords={quote(term)}&location={quote(location)}"
    if sort:
        u += f"&sortBy={sort}"          # DD = most recent, R = most relevant
    if hours:
        u += f"&f_TPR={TPR[hours]}"
    if start:
        u += f"&start={start}"
    return u


def _t(x):  # TextViewModel -> str
    return (x or {}).get("text")


def parse_cards(body):
    """JobCards json -> {id: card}. Precise listed time, Easy-Apply flag, repost flag."""
    inc = body.get("included", [])
    posting = {x["entityUrn"].rsplit(":", 1)[-1]: x for x in inc if x["$type"].endswith(".JobPosting")}
    out = {}
    for x in inc:
        urn = x.get("jobPostingUrn") or x.get("*jobPosting")
        if not x["$type"].endswith("JobPostingCard") or not x.get("jobPostingTitle") or not urn:
            continue
        jid = urn.rsplit(":", 1)[-1]
        ft = {i["type"]: i for i in x.get("footerItems") or []}
        out[jid] = dict(
            id=jid, title=x["jobPostingTitle"], company=_t(x.get("primaryDescription")),
            location=_t(x.get("secondaryDescription")), salary=_t(x.get("tertiaryDescription")),
            listed_ms=(ft.get("LISTED_DATE") or {}).get("timeAt"),      # refreshed on repost
            easy_apply_card="EASY_APPLY_TEXT" in ft,
            reposted=(posting.get(jid) or {}).get("repostedJob"))
    paging = (body.get("data") or {}).get("paging") or {}
    return out, paging.get("total")


def parse_details(body):
    """graphql prefetch json -> {id: {description, posted_on, onsite_apply, ats, apply_url, created_ms}}"""
    inc = body.get("included", [])
    out = {}
    def slot(x):
        return out.setdefault(x["entityUrn"].rsplit(":", 1)[-1], {})
    for x in inc:
        t = x["$type"]
        if t.endswith(".JobDescription"):
            s = slot(x); s["description"] = _t(x.get("descriptionText")); s["posted_on"] = x.get("postedOnText")
        elif t.endswith(".JobSeekerApplicationDetail"):
            s = slot(x)
            s.update(onsite_apply=x.get("onsiteApply"), ats=x.get("applicantTrackingSystemName"),
                     apply_url=x.get("companyApplyUrl"), apply_cta=_t(x.get("applyCtaText")))
        elif t.endswith(".JobPosting") and x.get("createdAt"):
            slot(x)["created_ms"] = x["createdAt"]
    return out


def apply_type(job):
    """native = Easy Apply, external = employer/ATS site. The list-card footer item EASY_APPLY_TEXT
    matched JobSeekerApplicationDetail.onsiteApply in 82/82 jobs checked (27 native, 55 external),
    so the card flag alone is a reliable no-click signal. External URL (apply_url) only exists for
    the ~24 prefetched cards per page load; otherwise read /jobs/view DOM: a[aria-label='Apply on company
    website'] href = linkedin.com/safety/go/?url=<urlencoded employer url> (read, never open)."""
    if job.get("onsite_apply") is not None:
        return "native" if job["onsite_apply"] else "external"
    return "native" if job.get("easy_apply_card") else "external"


def canonical_key(job):
    return f"linkedin:{job['id']}"          # numeric id == /jobs/view/<id>; reposts keep the id


def check(page, resp_status=None):
    if BAD_URL.search(page.url) or resp_status in (403, 429):
        raise Checkpoint(f"url/status: {page.url} {resp_status}")
    txt = page.evaluate("document.body ? document.body.innerText.slice(0,3000) : ''")
    if BAD_TEXT.search(txt):
        raise Checkpoint("challenge text on page")


def fetch_search(page, url, settle=7):
    """One page load. Returns (jobs {id: merged dict}, total, raw_bodies)."""
    keep = []
    def on(r):
        u = r.url
        if "voyager/api" in u and ("voyagerJobsDashJobCards" in u or "jobPostingDetailDescription" in u):
            keep.append(r)
    page.on("response", on)
    try:
        resp = page.goto(url, wait_until="domcontentloaded")
        check(page, resp.status if resp else None)
        time.sleep(settle)
        check(page)
        jobs, total, raws = {}, None, []
        for r in keep:
            try:
                body = r.json()
            except Exception:
                continue
            raws.append((r.url, body))
            if "/voyager/api/voyagerJobsDashJobCards?" in r.url:
                c, tot = parse_cards(body); total = tot or total
                for k, v in c.items(): jobs.setdefault(k, {}).update(v)
        for u, body in raws:
            if "/voyager/api/voyagerJobsDashJobCards?" not in u:
                for k, v in parse_details(body).items():
                    if k in jobs: jobs[k].update(v)
        return jobs, total, raws
    finally:
        page.remove_listener("response", on)


def main():
    term = sys.argv[1]; hours = int(sys.argv[sys.argv.index("--hours")+1]) if "--hours" in sys.argv else None
    start = int(sys.argv[sys.argv.index("--start")+1]) if "--start" in sys.argv else 0
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp("http://localhost:9222")
    page = b.contexts[0].new_page()                 # own tab
    try:
        jobs, total, _ = fetch_search(page, search_url(term, hours, start=start))
        print("total", total, "cards", len(jobs))
        for j in list(jobs.values())[:5]:
            j["desc_chars"] = len(j.pop("description", "") or ""); print(j, apply_type(j))
    finally:
        page.close(); b.close(); pw.stop()          # closes only our tab; Chrome untouched


if __name__ == "__main__":
    main()
