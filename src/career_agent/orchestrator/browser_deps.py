"""Playwright-backed browser ops for the step engine (kept thin; the engine
holds the logic)."""
from __future__ import annotations


from ..browser.clicks import pace, page_signature as _page_signature, settle_after_click as _settle_after_click


class BrowserDeps:
    def __init__(self, option_matcher=None):
        self.option_matcher = option_matcher   # rung-3 value->option llm (comboboxes)

    def snapshot(self, page):
        from ..browser.perception import snapshot_form
        return snapshot_form(page)

    def gate(self, page):
        from ..browser.gate_probe import classify_gate
        return classify_gate(page)

    def fill(self, page, decisions, revalidate: bool = True):
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
        if revalidate:
            from ..browser.filler import revalidate_invalid
            revalidate_invalid(page)

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
                    # no_wait_after: the click itself is the success. Waiting for the navigation it starts can
                    # time out on a slow page, and a retry would then click "Continue" a SECOND time on the next
                    # page (skipping a whole step of the form). Once the click went through, nothing below may retry.
                    pace(page)
                    before = _page_signature(page)
                    try:
                        fr.get_by_role(role, name=label, exact=False).first.click(timeout=3000, no_wait_after=True)
                    except Exception:
                        continue
                    try:
                        _settle_after_click(page, before)
                    except Exception:
                        pass
                    print(f"[click] {label!r}: {before[0][-60:]} -> {page.url[-60:]}", flush=True)
                    return
            if attempt == 0:
                # Button may be temporarily absent during an AJAX refresh — wait and retry once
                page.wait_for_timeout(2500)
                frames = [fr for fr in page.frames
                          if not any(s in (fr.url or "") for s in _SKIP)]
        raise RuntimeError(f"advance click failed: no {label!r} button/link in any frame")

    def confirmed(self, page):
        """(bool, why): did the submit really go through? Proof on the page, not the click."""
        from ..browser.confirmation import wait_for_confirmation
        return wait_for_confirmation(page)

    def url(self, page):
        return page.url
