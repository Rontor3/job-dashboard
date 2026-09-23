"""Live integration test for the rate limiter + portal state.

Steps:
  1. Scrape 10 LinkedIn data scientist jobs with external ATS (not Easy Apply)
  2. Run bulk against them with RATE_LIMIT_DOMAIN_DAY=1 so the second job
     from any domain triggers a defer
  3. Assert defer occurred + portal_state.json populated

Usage:
    PYTHONPATH=src python3 scripts/test_rate_limiter_live.py
    PYTHONPATH=src python3 scripts/test_rate_limiter_live.py --scrape-only
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

URLS_FILE  = ROOT / "data" / "rl_test_urls.json"
LOG_FILE   = ROOT / "data" / "bulk_run_log.json"
STATE_FILE = pathlib.Path.home() / ".career_agent" / "portal_state.json"
CDP_URL    = os.getenv("CAREER_AGENT_CDP_URL", "http://localhost:9222")


# ---------------------------------------------------------------------------
# Scrape LinkedIn for external-ATS data scientist jobs
# ---------------------------------------------------------------------------

def scrape_linkedin_jobs(n: int = 10) -> list[dict]:
    """Return up to n {title, company, url} dicts for DS jobs (all, incl Easy Apply).

    Easy Apply vs external is determined per-job in resolve_apply_url().
    """
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.goto(
            "https://www.linkedin.com/jobs/search/?keywords=data+scientist&location=India",
            wait_until="domcontentloaded", timeout=30000,
        )
        page.wait_for_timeout(3000)

        seen_urls: set[str] = set()
        scrolls = 0
        while len(results) < n * 3 and scrolls < 12:  # collect 3x; filter to external below
            cards_data = page.evaluate("""() => {
                const cards = document.querySelectorAll('li:has(a[href*="/jobs/view/"])');
                return Array.from(cards).map(li => {
                    const a = li.querySelector('a[href*="/jobs/view/"]');
                    const company = li.querySelector(
                        '.artdeco-entity-lockup__subtitle,.job-card-container__company-name');
                    return {
                        href: a?.href || '',
                        title: (a?.textContent || a?.getAttribute('aria-label') || '').trim().substring(0,60),
                        company: (company?.textContent || '').trim().substring(0,40),
                    };
                });
            }""")
            for card in cards_data:
                if len(results) >= n * 3:
                    break
                href = card.get("href", "")
                base = href.split("?")[0]
                if not base or base in seen_urls:
                    continue
                seen_urls.add(base)
                results.append({"title": card["title"], "company": card["company"], "url": href})
                print(f"  collected [{len(results)}] {card['title'][:40]} @ {card['company'][:20]}")
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(1500)
            scrolls += 1

        page.close()
    return results


# ---------------------------------------------------------------------------
# Resolve LinkedIn job card URLs → actual external ATS apply URL
# ---------------------------------------------------------------------------

def resolve_apply_url(li_url: str) -> str | None:
    """Open LinkedIn JD page; return the real external ATS URL, or None.

    LinkedIn wraps external apply links as:
      https://www.linkedin.com/safety/go/?url=<percent-encoded real url>
    Easy Apply jobs use a button (no external href).
    """
    from urllib.parse import unquote, urlparse, parse_qs
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(li_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)

            result = page.evaluate("""() => {
                // Easy Apply = button (not a link)
                const eaBtn = document.querySelector(
                    'button[aria-label*="Easy Apply"],button.jobs-apply-button');
                if (eaBtn) return {kind: 'easy_apply'};

                // External apply = LinkedIn safety-redirect link
                const safetyLinks = Array.from(document.querySelectorAll(
                    'a[href*="linkedin.com/safety/go"]'));
                for (const a of safetyLinks) {
                    const txt = (a.textContent || a.getAttribute('aria-label') || '').toLowerCase();
                    if (txt.includes('apply')) return {kind: 'external', href: a.href};
                }
                // No apply found (could be "I'm interested" or closed)
                return {kind: 'none'};
            }""")

            kind = result.get("kind", "none")
            if kind == "easy_apply":
                return None
            if kind == "external":
                raw_href = result.get("href", "")
                # Decode the real URL from LinkedIn safety redirect
                qs = parse_qs(urlparse(raw_href).query)
                real_url = unquote(qs.get("url", [""])[0])
                return real_url if real_url.startswith("http") else None
            return None
        except Exception as e:
            print(f"    [err] {e}")
            return None
        finally:
            page.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrape-only", action="store_true")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--pace", default="fast")
    args = ap.parse_args()

    # --- Step 1: Scrape ---
    if not URLS_FILE.exists() or args.scrape_only:
        print(f"\n=== Scraping LinkedIn data scientist jobs (want {args.n} external-ATS) ===")
        candidates = scrape_linkedin_jobs(args.n)
        print(f"\nResolving external apply URLs from {len(candidates)} candidates…")
        resolved = []
        for j in candidates:
            if len(resolved) >= args.n:
                break
            ext_url = resolve_apply_url(j["url"])
            if ext_url:
                j["apply_url"] = ext_url
                resolved.append(j)
                print(f"  ✓ {j['company'][:30]} → {ext_url[:60]}")
            else:
                print(f"  ✗ {j['company'][:30]} — Easy Apply / no external URL")
        URLS_FILE.write_text(json.dumps(resolved, indent=2))
        print(f"\nSaved {len(resolved)} external-ATS jobs to {URLS_FILE}")
        if args.scrape_only:
            return

    jobs = json.loads(URLS_FILE.read_text())
    if not jobs:
        print("No jobs scraped — aborting live test")
        sys.exit(1)
    print(f"\nLoaded {len(jobs)} jobs from {URLS_FILE}")

    # --- Step 2: Run bulk with domain cap = 1 ---
    print("\n=== Running bulk with RATE_LIMIT_DOMAIN_DAY=1 ===")
    os.environ["RATE_LIMIT_DOMAIN_DAY"] = "1"
    os.environ["RATE_LIMIT_HOUR"] = "20"  # high so hourly cap doesn't interfere

    bulk_file = _prep_bulk_input(jobs)
    print(f"Wrote {len(jobs)} URLs to {bulk_file}")

    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_bulk_applications.py"),
         "--urls-file", str(bulk_file),
         "--pace", args.pace],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"),
             "RATE_LIMIT_DOMAIN_DAY": "1"},
        cwd=str(ROOT),
        capture_output=False,
        text=True,
    )

    # --- Step 3: Assert ---
    print("\n=== Assertions ===")
    errors = []

    if LOG_FILE.exists():
        log = json.loads(LOG_FILE.read_text())
        deferred = [r for r in log if r["stopped_reason"] == "skipped_rate_limit"]
        print(f"  Total runs logged: {len(log)}")
        print(f"  Deferred/skipped:  {len(deferred)}")
        if not deferred:
            errors.append("FAIL: expected at least one defer with domain_cap=1 and multiple jobs per domain")
        else:
            print("  ✓ defer occurred")
    else:
        errors.append("FAIL: no log file written")

    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        print(f"  portal_state.json has {len(state)} domain entries")
        if not state:
            errors.append("FAIL: portal_state.json is empty")
        else:
            print("  ✓ portal state populated")
            for domain, entry in state.items():
                print(f"    {domain}: apps_today={entry['apps_today']} escalation={entry['escalation_count']}")
    else:
        errors.append("FAIL: portal_state.json not created")

    if errors:
        print("\nFAILED:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("\nAll assertions passed ✓")


# Write bulk input file in correct format, augmented with existing ATS jobs for defer coverage
def _prep_bulk_input(jobs):
    entries = [{"url": j["apply_url"]} for j in jobs if "apply_url" in j]

    # Pull in 4 more jobs from existing collection to get multi-domain coverage
    existing_file = ROOT / "data" / "job_urls_collected.json"
    if existing_file.exists():
        try:
            existing = json.loads(existing_file.read_text())
            # Pick 2 from greenhouse and 2 from lever to guarantee defers
            from urllib.parse import urlparse
            seen_domains: dict[str, int] = {}
            wanted = {"greenhouse.io": 2, "lever.co": 2}
            for j in existing:
                url = j.get("url", "")
                try:
                    netloc = urlparse(url).netloc
                    for key in wanted:
                        if key in netloc and seen_domains.get(key, 0) < wanted[key]:
                            seen_domains[key] = seen_domains.get(key, 0) + 1
                            entries.append({"url": url})
                            break
                except Exception:
                    continue
        except Exception:
            pass

    out = ROOT / "data" / "rl_test_bulk.json"
    out.write_text(json.dumps(entries, indent=2))
    return out


if __name__ == "__main__":
    main()
