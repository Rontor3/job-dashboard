"""Collect external ATS apply URLs from aimjobs.ai job search results.

Usage:
    PYTHONPATH=src python3 scripts/collect_aimjobs_urls.py
    PYTHONPATH=src python3 scripts/collect_aimjobs_urls.py --query "machine learning engineer" --n 20
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).parent.parent
CDP_URL = "http://localhost:9222"
OUT_FILE = ROOT / "data" / "aimjobs_urls.json"

# ATS domains we can actually handle — skip ones that are just company portals
# or known impossible gates (LinkedIn Easy Apply, Indeed, Glassdoor aggregators).
_SKIP_DOMAINS = ("linkedin.com", "indeed.com", "glassdoor.com", "naukri.com",
                 "monster.com", "shine.com", "instahyre.com", "iimjobs.com")


def _is_handleable(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    low = url.lower()
    return not any(d in low for d in _SKIP_DOMAINS)


def scrape(query: str, n: int = 20) -> list[dict]:
    from playwright.sync_api import sync_playwright

    results: list[dict] = []
    seen_ats: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()

        search_url = f"https://www.aimjobs.ai/Home/Search?q={query.replace(' ', '%20')}"
        page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)

        page_num = 1
        while len(results) < n:
            cards = page.query_selector_all("a[href*='/jobs/']")
            print(f"  [page {page_num}] {len(cards)} cards", flush=True)

            for card in cards:
                if len(results) >= n:
                    break
                href = card.get_attribute("href") or ""
                title_raw = (card.inner_text() or "").strip()[:80]

                # Click to open the detail panel
                try:
                    card.click()
                    page.wait_for_timeout(800)
                except Exception:
                    continue

                # Read data-job-url from the Apply button
                apply_btn = page.query_selector("button[data-job-url]")
                if not apply_btn:
                    # Try any element with data-job-url
                    apply_btn = page.query_selector("[data-job-url]")
                if not apply_btn:
                    continue

                ats_url = apply_btn.get_attribute("data-job-url") or ""
                if not _is_handleable(ats_url):
                    print(f"  skip {title_raw[:30]!r} → {ats_url[:50]}", flush=True)
                    continue

                # Deduplicate by ATS URL
                if ats_url in seen_ats:
                    continue
                seen_ats.add(ats_url)

                # Best-effort title / company from card text
                company = ""
                try:
                    company_el = card.query_selector("[class*='company'],[class*='employer']")
                    company = (company_el.inner_text() if company_el else "").strip()[:40]
                except Exception:
                    pass

                results.append({"url": ats_url, "title": title_raw, "company": company,
                                 "source": href})
                print(f"  ✓ [{len(results)}/{n}] {title_raw[:35]!r} → {ats_url[:55]}",
                      flush=True)

            if len(results) >= n:
                break

            # Paginate — click next page number button
            next_page = page_num + 1
            next_btn = None
            for el in page.query_selector_all(".pagination a, [class*='page'] a"):
                if el.inner_text().strip() == str(next_page):
                    next_btn = el
                    break
            if not next_btn:
                print("  no more pages", flush=True)
                break

            next_btn.click()
            page.wait_for_timeout(3000)
            page_num += 1

        page.close()

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="data scientist", help="Job search query")
    ap.add_argument("--n", type=int, default=20, help="Number of external URLs to collect")
    ap.add_argument("--out", default=str(OUT_FILE), help="Output JSON path")
    args = ap.parse_args()

    print(f"\n=== Collecting {args.n} aimjobs.ai URLs for '{args.query}' ===\n", flush=True)
    results = scrape(args.query, args.n)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved {len(results)} URLs to {out}")
    return results


if __name__ == "__main__":
    main()
