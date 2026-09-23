"""Collect 50 external job application URLs.

Source A (25): LinkedIn searches — external-apply only (f_AL=false excludes Easy Apply)
Source B (25): Google/web search for ATS job postings via known job-board patterns
"""
from __future__ import annotations
import json, time, re, sys
from pathlib import Path

CDP_URL = "http://localhost:9222"
OUT_FILE = Path(__file__).parent.parent / "data" / "job_urls_collected.json"

# ── LinkedIn queries (run separately, not combined) ──────────────────────────
LINKEDIN_QUERIES = [
    "data scientist",
    "machine learning engineer",
    "data analyst",
    "AI engineer",
    "machine learning engineer",
]

LINKEDIN_LOCATION = "India"   # change to "United+States" for US jobs

# ── Search queries for Source B (ATS direct-apply links) ────────────────────
SEARCH_QUERIES = [
    "machine learning engineer India site:jobs.lever.co",
    "data scientist India site:job-boards.greenhouse.io",
    "ML engineer India site:jobs.smartrecruiters.com",
    "data scientist India site:apply.workable.com",
    "AI engineer Bangalore Mumbai India site:lever.co OR site:greenhouse.io",
    "machine learning engineer India site:myworkdayjobs.com",
    "data scientist India site:jobs.ashbyhq.com",
]

def _wait(page, ms=2000):
    page.wait_for_timeout(ms)


def collect_linkedin(ctx, max_per_query: int = 7) -> list[dict]:
    collected: list[dict] = []
    seen: set[str] = set()

    for q in LINKEDIN_QUERIES:
        enc = q.replace(" ", "+")
        loc = LINKEDIN_LOCATION.replace(" ", "+")
        url = (f"https://www.linkedin.com/jobs/search/"
               f"?keywords={enc}&location={loc}&f_AL=false&f_TPR=r2592000")
        page = ctx.new_page()
        try:
            print(f"\n[linkedin] query: {q!r}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            _wait(page, 3000)

            cards = page.query_selector_all(
                ".job-card-container__link, .jobs-search-results__list-item a[href*='/jobs/']")
            print(f"  found {len(cards)} cards")

            for card in cards[:max_per_query]:
                try:
                    card.click()
                    _wait(page, 1500)
                    # apply button detection
                    btn = page.query_selector(
                        ".jobs-apply-button--top-card button, "
                        ".jobs-s-apply button, "
                        "[data-control-name='jobdetails_topcard_inapply']")
                    if not btn:
                        continue
                    btn_text = (btn.inner_text() or "").strip().lower()
                    if "easy apply" in btn_text:
                        continue  # skip LinkedIn Easy Apply
                    # external apply — new tab
                    with ctx.expect_page(timeout=10000) as new_info:
                        btn.click()
                    new_page = new_info.value
                    new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                    ext_url = new_page.url
                    new_page.close()
                    if (ext_url and ext_url not in seen
                            and "linkedin.com" not in ext_url
                            and ext_url.startswith("http")):
                        seen.add(ext_url)
                        collected.append({"source": "linkedin", "query": q, "url": ext_url})
                        print(f"  [+] {ext_url[:90]}")
                    _wait(page, 1000)
                except Exception as e:
                    print(f"  [skip card] {e!r}"[:80])
        except Exception as e:
            print(f"  [skip query] {e!r}"[:80])
        finally:
            page.close()
        time.sleep(2)

    return collected


def collect_search(ctx, max_per_query: int = 5) -> list[dict]:
    """Use DuckDuckGo (no bot-check) to find direct ATS apply links."""
    collected: list[dict] = []
    seen: set[str] = set()

    ATS_PATTERNS = re.compile(
        r"https?://(?:[a-z0-9-]+\.)?"
        r"(?:lever\.co|greenhouse\.io|myworkdayjobs\.com|"
        r"apply\.workable\.com|jobs\.ashbyhq\.com|boards\.greenhouse\.io|"
        r"jobs\.smartrecruiters\.com|[a-z0-9]+\.applytojob\.com|"
        r"icims\.com|taleo\.net|successfactors\.com|oraclecloud\.com)/",
        re.I)

    for q in SEARCH_QUERIES:
        enc = q.replace(" ", "+")
        ddg_url = f"https://duckduckgo.com/?q={enc}&ia=web"
        page = ctx.new_page()
        try:
            print(f"\n[search] query: {q!r}")
            page.goto(ddg_url, timeout=30000, wait_until="domcontentloaded")
            _wait(page, 2500)
            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e=>e.href).filter(h=>h.startsWith('http'))")
            ats_links = [l for l in links if ATS_PATTERNS.search(l) and l not in seen]
            for link in ats_links[:max_per_query]:
                seen.add(link)
                collected.append({"source": "search", "query": q, "url": link})
                print(f"  [+] {link[:90]}")
        except Exception as e:
            print(f"  [skip] {e!r}"[:80])
        finally:
            page.close()
        time.sleep(1.5)

    return collected


def main():
    from playwright.sync_api import sync_playwright

    print("=== Collecting job URLs ===")
    all_collected: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]

        # Source A: LinkedIn
        print("\n── Source A: LinkedIn (external apply only) ──")
        linkedin_jobs = collect_linkedin(ctx, max_per_query=7)
        all_collected.extend(linkedin_jobs)
        print(f"LinkedIn collected: {len(linkedin_jobs)}")

        # Source B: Web search
        print("\n── Source B: Web search (ATS links) ──")
        search_jobs = collect_search(ctx, max_per_query=5)
        all_collected.extend(search_jobs)
        print(f"Search collected: {len(search_jobs)}")

    # Deduplicate by URL
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for job in all_collected:
        if job["url"] not in seen_urls:
            seen_urls.add(job["url"])
            deduped.append(job)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(deduped, indent=2))
    print(f"\n=== Total unique URLs: {len(deduped)} → {OUT_FILE} ===")
    for i, j in enumerate(deduped, 1):
        print(f"  {i:2d}. [{j['source']}] {j['url'][:80]}")


if __name__ == "__main__":
    main()
