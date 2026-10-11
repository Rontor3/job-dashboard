"""Playwright-backed browser ops for the step engine (kept thin; the engine
holds the logic)."""
from __future__ import annotations


from ..browser.clicks import (pace, page_signature as _page_signature, settle_after_click as _settle_after_click,
                              timeout_ms, wait)


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
            wait(page, 1000)              # let DOM show the file input after radio click
        if uploads:
            # Upload resume first; many ATS platforms parse it and auto-fill
            # name/email/phone/LinkedIn — wait for that before we overwrite.
            # A résumé upload makes many sites parse it and fill name/email/LinkedIn themselves: wait for that to
            # finish, then write ours over it. Their parse is a guess (Zoho made "linkedin.com/in/x, https://
            # linkedin.com/in" of a LinkedIn URL); ours is what the candidate saved.
            apply_decisions(page, uploads, matcher=self.option_matcher)
            wait(page, 2500)
        apply_decisions(page, rest, matcher=self.option_matcher)
        _retype_what_did_not_stick(page, rest)
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
                        fr.get_by_role(role, name=label, exact=False).first.click(timeout=timeout_ms(3000), no_wait_after=True)
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
                wait(page, 2500)
                frames = [fr for fr in page.frames
                          if not any(s in (fr.url or "") for s in _SKIP)]
        raise RuntimeError(f"advance click failed: no {label!r} button/link in any frame")

    def confirmed(self, page):
        """(bool, why): did the submit really go through? Proof on the page, not the click."""
        from ..browser.confirmation import wait_for_confirmation
        return wait_for_confirmation(page)

    def url(self, page):
        return page.url


def _retype_what_did_not_stick(page, decisions) -> list[str]:
    """A typed value the page doesn't show (a framework that ignores a programmatic fill, a box re-rendered after we
    typed) was reported as filled anyway. Read every text fill back; retype a blank one with real keystrokes once,
    and name what is still blank in the log. Returns those labels."""
    from ..browser.filler import read_back, frame_target
    texts = [d for d in decisions if d.action == "fill" and d.value not in (None, "")]
    shown = read_back(page, texts)
    lost, fresh = [], None
    for d in texts:
        if str(shown.get(d.ref, "")).strip():
            continue                                   # it holds a value
        try:
            target, sel = frame_target(page, d.ref)
            if target.locator(sel).count() == 0:
                # the page re-drew this part after we typed (Zoho re-renders its consent block when the box is
                # ticked): the old element is gone, so find the same question again
                if fresh is None:
                    from ..browser.perception import collect_raw, to_form_model
                    fresh = to_form_model(collect_raw(page))
                twin = next((f for f in fresh if f.label == d.label and f.kind == d.kind), None)
                if twin is None:
                    continue
                d = type(d)(twin.ref, d.kind, d.label, d.value, d.action, d.source)
                target, sel = frame_target(page, d.ref)
            box = target.locator(sel).first
            box.click(timeout=3000)
            box.press_sequentially(str(d.value), delay=15, timeout=15000)
            box.press("Tab")
        except Exception:
            pass
        if not str(read_back(page, [d]).get(d.ref, "")).strip():
            lost.append(d.label)
    if lost:
        print(f"[fill] did not stick: {lost}", flush=True)
    return lost
