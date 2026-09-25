"""Wellfound logged-in feed fetch (verified 2026-09-25). Read-only; own tab; paced.

Method: load https://wellfound.com/jobs once in the logged-in CDP Chrome, capture the app's own
persisted-query request headers (x-apollo-signature, x-wf-cfp, ...), then replay the app's own
`JobSearchResultsX` operation from inside the page with modified variables (page / sortBy /
locationTagIds / customJobTitles / keywords / hideOffPlatformJobs). Full description is in the payload.
No time filter exists server-side: sortBy=LAST_POSTED + client-side cutoff on liveStartAt.
"""
import gzip, json, random, sys, time
from playwright.sync_api import sync_playwright

OP = "tfe/5f366cd305b4f13cf6098df75f7ff2bb92fa42b9a74cb3a3aec7bdc69c6b051e"  # JobSearchResultsX (may rotate on deploys: re-capture from the page's own request)
INDIA = "1647"  # NewTag id for India (from public role page apolloState)
KEEP = {"x-apollo-signature", "x-wf-cfp", "x-angellist-dd-client-referrer-resource",
        "x-requested-with", "apollographql-client-name", "content-type"}


def canonical_key(job) -> str:
    return f"wellfound:{job['id']}"          # numeric JobListing id, stable across sessions & feed/public pages


def canonical_url(job) -> str:
    return f"https://wellfound.com/jobs/{job['id']}-{job['slug']}"


def is_external(job) -> bool:                # autoPosted==True <=> removed by hideOffPlatformJobs (6/6 verified)
    return bool(job.get("autoPosted"))


class Feed:
    def __init__(self, cdp="http://localhost:9222"):
        self.pw = sync_playwright().start()
        self.b = self.pw.chromium.connect_over_cdp(cdp)
        self.page = self.b.contexts[0].new_page()     # own tab
        self.hdr = None
        self.page.on("request", self._on_req)

    def _on_req(self, r):
        if "graphql" not in r.url or not r.post_data_buffer:
            return
        b = r.post_data_buffer
        b = gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b
        if b"JobSearchResultsX" in b:
            self.hdr = {k: v for k, v in r.all_headers().items() if k.lower() in KEEP}

    def open(self):
        self.page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded")
        self.page.wait_for_timeout(7000)      # NOTE: sync playwright only pumps events inside its own calls -> never time.sleep
        if not self.hdr:
            raise RuntimeError("feed request not seen: logged out / challenge? STOP, do not retry")

    def query(self, page=1, sort="LAST_POSTED", location=INDIA, title=None, keywords=None, hide_offplatform=False):
        f = {"page": page, "equity": {"min": None, "max": None}, "remotePreference": "NO_REMOTE",
             "salary": {"min": None, "max": None}, "yearsExperience": {"min": None, "max": None},
             "sortBy": sort, "hideOffPlatformJobs": hide_offplatform}
        if location: f["locationTagIds"] = [location]
        if title: f["customJobTitles"] = [title]        # strict-ish title match
        if keywords: f["keywords"] = [keywords]         # broader (description) match
        h = dict(self.hdr, **{"x-apollo-operation-name": "JobSearchResultsX"})
        body = json.dumps({"operationName": "JobSearchResultsX",
                           "variables": {"filterConfigurationInput": f}, "extensions": {"operationId": OP}})
        st, txt = self.page.evaluate(
            "async([b,h])=>{const r=await fetch('/graphql',{method:'POST',credentials:'include',headers:h,body:b});"
            "return [r.status,await r.text()]}", [body, h])
        if st in (401, 403, 429) or st >= 500:
            raise RuntimeError(f"HTTP {st}: throttled/challenged -> stop")
        j = json.loads(txt)
        if j.get("errors"):
            raise RuntimeError(j["errors"][0]["message"])
        r = j["data"]["talent"]["jobSearchResults"]
        jobs = []
        for e in r["startups"]["edges"]:                # 10 startups/page, <=3 highlighted jobs each
            n = e["node"]
            for x in n["highlightedJobListings"]:
                jobs.append({**x, "company": n["name"], "startupId": n["startupId"], "startupSlug": n["slug"]})
        return jobs, r["totalStartupCount"], r["hasNextPage"]

    def recent(self, days=7, max_pages=40, **kw):
        """Newest-first walk; stop after 2 consecutive pages with no job inside the window."""
        cutoff, out, stale, seen = time.time() - days * 86400, {}, 0, set()
        for pg in range(1, max_pages + 1):
            jobs, _, nxt = self.query(page=pg, **kw)
            fresh = [x for x in jobs if x["liveStartAt"] >= cutoff]
            for x in fresh: out[canonical_key(x)] = x
            stale = 0 if fresh else stale + 1
            if stale >= 2 or not nxt: break
            self.page.wait_for_timeout(int(random.uniform(3000, 7000)))
        return list(out.values())

    def close(self):
        self.page.close(); self.b.close(); self.pw.stop()      # only our tab


if __name__ == "__main__":
    f = Feed(); f.open()
    try:
        js = f.recent(days=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
        print(len(js), "jobs; external:", sum(map(is_external, js)))
        for x in js[:5]:
            print(canonical_key(x), x["title"], "|", x["company"], "|", x["locationNames"], "| desc chars", len(x["description"]))
    finally:
        f.close()
