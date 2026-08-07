"""Selenium-driven LinkedIn content-search fetcher (read-only).

Raw HTTP to LinkedIn is Cloudflare-bot-walled; a real Chrome executes the JS
challenge and loads normally. We authenticate with the candidate's own cookies
(no password, no login automation), navigate the content-search page per
keyword, scroll with human-paced random delays, and parse the rendered HTML.
Selenium is imported lazily so the module imports/tests without a browser.
Never logs cookie values.
"""
from __future__ import annotations

import random
import time
import urllib.parse

from job_dashboard.linkedin.post_parse import parse_posts_html

_LOGIN_MARKERS = ("/login", "/authwall", "/checkpoint", "/uas/login")


class LinkedInAuthError(RuntimeError):
    """Cookies missing/expired — session landed on a login/authwall page."""


def _default_driver_factory(headless: bool):
    def factory():
        # Prefer undetected-chromedriver: it hides the automation fingerprints
        # (navigator.webdriver, CDP tells) that LinkedIn's bot detection checks
        # for. Falls back to plain Selenium if it isn't installed. Everything is
        # imported lazily so unit tests (which inject a fake driver_factory)
        # need neither a browser nor these packages.
        try:
            import ssl
            import certifi
            # uc downloads a patched chromedriver on first run; point the
            # default HTTPS context at a real CA bundle so that download works
            # on macOS pythons that lack a usable system bundle.
            ssl._create_default_https_context = (
                lambda *a, **k: ssl.create_default_context(cafile=certifi.where()))
            import undetected_chromedriver as uc
            opts = uc.ChromeOptions()
            opts.add_argument("--window-size=1280,900")
            return uc.Chrome(options=opts, headless=headless)
        except Exception:  # noqa: BLE001 — uc missing/failed → plain Selenium
            from selenium import webdriver
            opts = webdriver.ChromeOptions()
            if headless:
                opts.add_argument("--headless=new")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1280,900")
            opts.add_argument(
                "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
            return webdriver.Chrome(options=opts)
    return factory


class LinkedInBrowserFetcher:
    def __init__(self, li_at, jsessionid, *, driver_factory=None, headless=False,
                 max_scrolls=5, sleep=None):
        self._li_at = li_at
        self._jsessionid = str(jsessionid).strip().strip('"')
        self._driver_factory = driver_factory or _default_driver_factory(headless)
        self._max_scrolls = max_scrolls
        self._sleep = sleep or (lambda: time.sleep(random.uniform(2.0, 5.0)))

    def _nap(self):
        # tolerate both no-arg and value styles of injected sleep
        try:
            self._sleep()
        except TypeError:
            self._sleep(0)

    def search_posts(self, keyword, *, date_posted="past-24h"):
        driver = self._driver_factory()
        try:
            driver.get("https://www.linkedin.com")
            for name, value in (("li_at", self._li_at),
                                ("JSESSIONID", f'"{self._jsessionid}"')):
                driver.add_cookie({"name": name, "value": value,
                                   "domain": ".linkedin.com"})
            self._nap()
            kw = urllib.parse.quote(keyword)
            driver.get(
                "https://www.linkedin.com/search/results/content/"
                f"?keywords={kw}&datePosted=%22{date_posted}%22&origin=FACETED_SEARCH")
            self._nap()
            if any(m in (driver.current_url or "") for m in _LOGIN_MARKERS):
                raise LinkedInAuthError(
                    "LinkedIn session expired — re-paste li_at/JSESSIONID from your browser")
            for _ in range(self._max_scrolls):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self._nap()
            return parse_posts_html(driver.page_source)
        finally:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
