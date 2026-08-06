"""Cookie-authenticated LinkedIn Voyager client (read-only).

Uses the candidate's own browser session cookies (li_at, JSESSIONID) from .env
to call LinkedIn's internal Voyager API. No writes, no login automation. Never
logs cookie values. All HTTP goes through an injectable ``fetch`` seam so tests
never touch the network.
"""
from __future__ import annotations

import json
import ssl
import urllib.request

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

try:  # macOS python often lacks a usable default CA bundle
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()


class LinkedInAuthError(RuntimeError):
    """Cookies missing/expired — the caller should tell the user to re-paste."""


class LinkedInRateLimit(RuntimeError):
    """LinkedIn returned 429 — back off and try later."""


def _urllib_fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class VoyagerClient:
    BASE = "https://www.linkedin.com"

    def __init__(self, li_at, jsessionid, *, fetch=None):
        # env.py strips the surrounding quotes on load, so jsessionid is the
        # bare ``ajax:...`` value here. csrf-token wants it bare; the Cookie
        # header wants it re-quoted.
        csrf = jsessionid.strip().strip('"')
        self._fetch = fetch or _urllib_fetch
        self.headers = {
            "User-Agent": _UA,
            "Accept": "application/vnd.linkedin.normalized+json+2.1",
            "x-restli-protocol-version": "2.0.0",
            "x-li-lang": "en_US",
            "csrf-token": csrf,
            "Cookie": f'li_at={li_at}; JSESSIONID="{csrf}"',
        }

    def _get_json(self, url):
        status, body = self._fetch(url, self.headers)
        if status in (301, 302, 401, 403):
            raise LinkedInAuthError(
                "LinkedIn cookie expired — re-paste li_at/JSESSIONID from your browser"
            )
        if status == 429:
            raise LinkedInRateLimit("LinkedIn rate-limited the request — try again later")
        if status != 200:
            raise RuntimeError(f"LinkedIn returned HTTP {status}")
        try:
            return json.loads(body)
        except ValueError:
            return {}

    def me(self):
        return self._get_json(f"{self.BASE}/voyager/api/me")
