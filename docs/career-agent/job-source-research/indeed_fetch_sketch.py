"""UNVERIFIED sketch — Indeed blocked the CDP session with a Cloudflare Turnstile challenge (see report.md).
Written from known Indeed page structure; nothing here was tested against live results.
Bails out on any challenge page rather than retrying."""
import json, random, re, time
from playwright.sync_api import sync_playwright

def blocked(page):
    return page.title().startswith("Just a moment") or "turnstile" in page.content()[:60000]

def search(page, term, fromage=None, start=0):
    q = f"https://in.indeed.com/jobs?q={term.replace(' ','+')}&l=India&sort=date&start={start}"
    if fromage: q += f"&fromage={fromage}"
    page.goto(q, wait_until="domcontentloaded"); page.wait_for_timeout(2500)
    if blocked(page): raise RuntimeError("cloudflare challenge - stop, human needed")
    # expected (unverified): cards embedded as JSON in script#mosaic-data / window.mosaic.providerData["mosaic-provider-jobcards"]
    data = page.evaluate("()=>window.mosaic&&window.mosaic.providerData&&window.mosaic.providerData['mosaic-provider-jobcards']")
    results = (data or {}).get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results", [])
    return [{"key": r.get("jobkey"), "title": r.get("title"), "company": r.get("company"),
             "posted_raw": r.get("formattedRelativeTime"), "sponsored": r.get("sponsored")} for r in results]

if __name__ == "__main__":
    pw = sync_playwright().start(); b = pw.chromium.connect_over_cdp("http://localhost:9222")
    page = b.contexts[0].new_page()
    try: print(json.dumps(search(page, "data scientist", fromage=3), indent=1))
    finally: page.close(); b.close(); pw.stop()
