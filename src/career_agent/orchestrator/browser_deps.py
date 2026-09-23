"""Playwright-backed browser ops for the step engine (kept thin; the engine
holds the logic)."""
from __future__ import annotations


class BrowserDeps:
    def __init__(self, option_matcher=None):
        self.option_matcher = option_matcher   # rung-3 value->option llm (comboboxes)

    def snapshot(self, page):
        from ..browser.perception import snapshot_form
        return snapshot_form(page)

    def gate(self, page):
        from ..browser.gate_probe import classify_gate
        return classify_gate(page)

    def fill(self, page, decisions):
        from ..browser.filler import apply_decisions, read_back
        # Radio selections (check_group) that reveal a file input must run BEFORE uploads.
        radio_sel = [d for d in decisions if d.action == "check_group"
                     and d.source == "resume"]
        uploads   = [d for d in decisions if d.action == "upload"]
        rest      = [d for d in decisions if d.action not in ("upload",)
                     and d not in radio_sel]
        if radio_sel:
            apply_decisions(page, radio_sel, matcher=self.option_matcher)
            page.wait_for_timeout(1000)   # let DOM show the file input after radio click
        if uploads:
            # Upload resume first; many ATS platforms parse it and auto-fill
            # name/email/phone/LinkedIn — wait for that before we overwrite.
            apply_decisions(page, uploads, matcher=self.option_matcher)
            page.wait_for_timeout(2500)
            prefilled = read_back(page, rest)
            rest = [d for d in rest if not prefilled.get(d.ref)]
        apply_decisions(page, rest, matcher=self.option_matcher)

    def read_back(self, page, decisions):
        from ..browser.filler import read_back
        return read_back(page, decisions)

    def click(self, page, label):
        from ..browser.page_prep import prepare
        prepare(page)   # dismiss cookie/idle overlays before clicking advance
        # Scan all non-captcha frames — the advance button may live inside an
        # embedded ATS iframe (e.g. iCIMS), invisible to page.get_by_role().
        _SKIP = ("hcaptcha.com", "recaptcha", "googletagmanager",
                 "google-analytics", "doubleclick", "challenges.cloudflare")
        frames = [fr for fr in page.frames
                  if not any(s in (fr.url or "") for s in _SKIP)]
        for attempt in range(2):
            for role in ("button", "link"):
                for fr in frames:
                    try:
                        fr.get_by_role(role, name=label, exact=False).first.click(timeout=3000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                        page.wait_for_timeout(3000)   # settle: SPA re-render after nav click
                        return
                    except Exception:
                        pass
            if attempt == 0:
                # Button may be temporarily absent during an AJAX refresh — wait and retry once
                page.wait_for_timeout(2500)
                frames = [fr for fr in page.frames
                          if not any(s in (fr.url or "") for s in _SKIP)]
        raise RuntimeError(f"advance click failed: no {label!r} button/link in any frame")

    def url(self, page):
        return page.url
