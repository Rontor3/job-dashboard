# LinkedIn External Job Search

Collect external-apply job URLs from LinkedIn using multiple focused queries.
Run these steps via CDP-connected Chrome (Playwright) or Claude in Chrome.

## Rules
- **Never combine queries** — run each as a separate search to avoid LinkedIn's OR-bias
- **External only** — skip any job whose Apply button is LinkedIn Easy Apply; we want "Apply on company website"
- **Deduplicate** — track collected URLs in a set; skip if already seen
- **Rate-limit** — wait 2–3s between page navigations to avoid rate-limiting

## Queries to run (in order)
1. "data scientist"
2. "machine learning engineer"
3. "data analyst"
4. "ML engineer"
5. "AI engineer"
6. "data science intern"
7. "machine learning intern"

## LinkedIn filters to apply (after each search)
- Date posted: Past month (f_TPR=r2592000)
- Job type: Full-time or Internship
- Easy Apply: OFF — use URL param `f_AL=false` to exclude Easy Apply
- Location: United States

## Search URL pattern
```
https://www.linkedin.com/jobs/search/?keywords=<QUERY>&location=United+States&f_AL=false&f_TPR=r2592000
```
`f_AL=false` excludes Easy Apply → only external-apply jobs remain.

## Per-job extraction workflow
1. Navigate to search results URL
2. Wait for job cards to load (wait for `.jobs-search-results__list-item`)
3. For each card (up to 10 per query):
   a. Click the card to open the right panel
   b. Wait 1s for the panel to load
   c. Check the Apply button text:
      - "Apply on company website" or "Apply" (no Easy Apply badge) → KEEP
      - "Easy Apply" → SKIP
   d. For KEEP: click "Apply on company website" — capture the new tab URL
   e. Add that URL to the collected list
   f. Close the new tab
4. Scroll down, click "Next page" if needed, repeat
5. Move to next query

## Extraction code (Playwright CDP)
```python
from playwright.sync_api import sync_playwright
import time, re

QUERIES = [
    "data scientist",
    "machine learning engineer",
    "data analyst",
    "ML engineer",
    "AI engineer",
]

def collect_linkedin_jobs(max_per_query=10):
    collected = []
    seen = set()
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        for q in QUERIES:
            url = f"https://www.linkedin.com/jobs/search/?keywords={q.replace(' ', '+')}&location=United+States&f_AL=false&f_TPR=r2592000"
            page = ctx.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            cards = page.query_selector_all(".jobs-search-results__list-item, .job-card-container")
            for card in cards[:max_per_query]:
                try:
                    card.click()
                    page.wait_for_timeout(1500)
                    # Check apply button
                    btn = page.query_selector(".jobs-apply-button, [data-control-name='jobdetails_topcard_inapply']")
                    if not btn:
                        continue
                    btn_text = (btn.text_content() or "").strip().lower()
                    if "easy apply" in btn_text:
                        continue
                    # External apply — click and capture new tab
                    with ctx.expect_page() as new_page_info:
                        btn.click()
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                    ext_url = new_page.url
                    new_page.close()
                    if ext_url and ext_url not in seen and "linkedin.com" not in ext_url:
                        seen.add(ext_url)
                        collected.append({"query": q, "url": ext_url})
                        print(f"  [+] {ext_url[:80]}")
                except Exception as e:
                    print(f"  [skip] {e!r:.60}")
            page.close()
            time.sleep(2)
    return collected
```

## After collection
Feed collected URLs into the career agent:
```bash
for url in COLLECTED_URLS:
    PYTHONPATH=src python3 -m career_agent.apply --url "$url" --cdp-url http://localhost:9222
```
