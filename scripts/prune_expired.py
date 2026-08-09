"""Daily expiry sweep — soft-hide closed / stale / bad-fit jobs.

    python3 scripts/prune_expired.py            # HTTP sources + LinkedIn/Naukri (needs cookies)
    python3 scripts/prune_expired.py --no-browser   # skip the browser checks

Zero LLM tokens. LinkedIn/Naukri are bot-walled over plain HTTP, so those are
checked with a headless real browser (undetected-chromedriver) — and only for
jobs whose LLM score clears --llm-gate (default 50), to save time.
"""
import argparse
import os
import ssl
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from job_dashboard.env import load_env_file  # noqa: E402
from job_dashboard.db import init_db  # noqa: E402
from job_dashboard.match.liveness import sweep, CLOSED_MARKERS  # noqa: E402


def build_browser_check(li_at, jsessionid):
    """A closure that loads a bot-walled job URL in one reused headless Chrome
    and reports open/closed. Returns (check, close)."""
    try:
        import certifi
        ssl._create_default_https_context = (
            lambda *a, **k: ssl.create_default_context(cafile=certifi.where()))
    except Exception:  # noqa: BLE001
        pass
    import undetected_chromedriver as uc
    driver = uc.Chrome(options=uc.ChromeOptions(), headless=True)
    driver.get("https://www.linkedin.com")
    if li_at:
        driver.add_cookie({"name": "li_at", "value": li_at, "domain": ".linkedin.com"})
    if jsessionid:
        bare = jsessionid.strip().strip('"')
        driver.add_cookie({"name": "JSESSIONID", "value": f'"{bare}"',
                           "domain": ".linkedin.com"})

    def check(url):
        try:
            driver.get(url)
            time.sleep(2.5)
            low = (driver.page_source or "").lower()
            if any(m in low for m in CLOSED_MARKERS):
                return False
            return True
        except Exception:  # noqa: BLE001
            return None

    return check, driver.quit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--llm-gate", type=int, default=50)
    ap.add_argument("--max-age-days", type=int, default=45)
    ap.add_argument("--min-ctc-lpa", type=float, default=25,
                    help="hide roles whose stated annual CTC is below this (LPA)")
    args = ap.parse_args()

    load_env_file(".env")
    conn = init_db(args.db)
    li = os.getenv("LINKEDIN_LI_AT")
    js = os.getenv("LINKEDIN_JSESSIONID")

    browser_check = close = None
    if not args.no_browser and li and js:
        try:
            browser_check, close = build_browser_check(li, js)
        except Exception as e:  # noqa: BLE001
            print(f"browser check unavailable ({e}); pruning HTTP sources + age/bad-fit only")

    try:
        counts = sweep(conn, browser_check=browser_check, llm_gate=args.llm_gate,
                       max_age_days=args.max_age_days, min_ctc_lpa=args.min_ctc_lpa,
                       on_progress=lambda j: None)
    finally:
        if close:
            try:
                close()
            except Exception:  # noqa: BLE001
                pass

    print(f"expiry sweep done: {counts}")


if __name__ == "__main__":
    main()
