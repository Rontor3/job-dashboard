"""RemoteSolveSession — assembles a remote-solve: mint token, start the CDP
screencast + live-view server, hand back a single-use link, then run the
MAIN-thread pump that (a) applies viewer taps to the page via sync Playwright
and (b) polls for the human's solve. `close()` tears it all down.

The pump lives here, on the main thread, because Playwright's sync API is
thread-affine — pointer events collected by the server thread must be applied
here, not there.
"""
from __future__ import annotations

import os
import queue
import time

# Injected into the page: latch a flag the instant a captcha response token
# appears. The token is the only unambiguous proof of a solve, but on a SPA it
# can vanish within a poll interval as the view advances — so we watch it from
# INSIDE the page at 50ms and set a window flag that survives the view swap.
#
# `watch_g`/`watch_h` select WHICH token latches. On a page carrying BOTH a
# reCAPTCHA and an hCaptcha (e.g. Oracle's email step), an auto/v3 reCAPTCHA
# token latches while the hCaptcha the human is actually solving is still
# pending — a false "cleared". So for an hCaptcha gate we watch only the
# hCaptcha token, and vice-versa.
def _observer_body(watch_g: bool = True, watch_h: bool = True) -> str:
    setter = []
    poll = []
    if watch_g:
        setter.append("this.id === 'g-recaptcha-response'")
        poll.append("(r && r.value)")
    if watch_h:
        setter.append("this.name === 'h-captcha-response'")
        poll.append("(h && h.value)")
    setter_cond = " || ".join(setter) or "false"
    poll_cond = " || ".join(poll) or "false"
    return r"""
  if (window.__cca_installed) return;
  window.__cca_installed = true;
  function __ccaLatch() {
    window.__cca_cleared = true;
    try { localStorage.setItem('__cca_cleared', '1'); } catch (e) {}
  }
  // Layer 1: hook the textarea value setter, so we catch the response token the
  // instant it is written — even if the page consumes it a moment later.
  try {
    var desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
    if (desc && desc.set && !desc.set.__cca) {
      var orig = desc.set;
      var wrapped = function (v) {
        orig.call(this, v);
        if (v && (%s)) __ccaLatch();
      };
      wrapped.__cca = true;
      Object.defineProperty(HTMLTextAreaElement.prototype, 'value',
        { set: wrapped, get: desc.get, configurable: true, enumerable: desc.enumerable });
    }
  } catch (e) {}
  // Layer 2: also poll, in case the token is set via a path that skips the setter.
  setInterval(function () {
    var r = document.querySelector('textarea#g-recaptcha-response');
    var h = document.querySelector('textarea[name="h-captcha-response"]');
    if (%s) __ccaLatch();
  }, 50);
""" % (setter_cond, poll_cond)

from .token import mint_token, build_url
from .server import LiveViewServer

_DEBUG = bool(os.getenv("CAREER_AGENT_LIVEVIEW_DEBUG"))


class RemoteSolveSession:
    def __init__(self, page, host, port, ttl_s, allow_public, is_cleared,
                 clock=time.time, sleep=time.sleep, poll_interval_s=0.3,
                 frame_slice_ms=40, resolve_absence_s=3.5, captcha_kind=None,
                 interactive=False):
        # interactive=True: a review/EDIT session (tap + TYPE the real form),
        # completed only by the human's "Done"/Submit — not a captcha token, so
        # a no-captcha form doesn't false-complete via the absence timer.
        self.interactive = interactive
        # captcha_kind selects which token latches "cleared". None = watch both
        # (back-compat). An hcaptcha_* gate watches only the hCaptcha token so a
        # co-present reCAPTCHA token can't false-clear it, and vice-versa.
        self._watch_g = captcha_kind is None or str(captcha_kind).startswith("recaptcha")
        self._watch_h = captcha_kind is None or str(captcha_kind).startswith("hcaptcha")
        self._resolve_absence_s = resolve_absence_s
        self.page = page
        self.host = host
        self.port = port
        self.ttl_s = ttl_s
        self.allow_public = allow_public
        self.is_cleared = is_cleared          # callable(page) -> bool
        self._clock = clock
        self._sleep = sleep
        self.poll_interval_s = poll_interval_s
        self._frame_slice_ms = frame_slice_ms
        self._pointer_q = queue.Queue()
        self._human_done = False
        self._cdp = None
        self._server = None

    def start(self) -> str:
        # Import the CDP bridge lazily so this module imports without Playwright.
        from career_agent.browser.live_view.cdp_bridge import start_screencast

        self._token = mint_token(self.ttl_s, self._clock())
        # Enforces private-by-default (raises on a public host without opt-in).
        url = build_url(self.host, self.port, self._token.value, self.allow_public)
        self._server = LiveViewServer(
            self.page, self._token, self.host, self.port, self._pointer_q)
        self._cdp = start_screencast(self.page, self._server.push_frame)
        try:
            # Clear any stale flag from a prior session on this origin, then
            # install the token observer (add_init_script re-runs it on every
            # navigation; evaluate covers the already-loaded page).
            body = _observer_body(self._watch_g, self._watch_h)
            self.page.evaluate("() => { try { localStorage.removeItem('__cca_cleared'); } catch (e) {} }")
            self.page.add_init_script("(function () {%s})();" % body)
            self.page.evaluate("() => {%s}" % body)
        except Exception:
            pass
        self._server.start()
        return url

    def wait_until_cleared(self, timeout_s) -> bool:
        from career_agent.browser.live_view.cdp_bridge import forward_pointer
        from career_agent.browser.gate_probe import classify_gate

        vp = self.page.viewport_size or {"width": 900, "height": 1600}
        start = self._clock()
        last_check = 0.0
        gone_since = None
        while self._clock() - start < timeout_s:
            # Apply queued taps immediately (low input latency).
            self._drain_pointers(forward_pointer, vp)
            if self._human_done:          # human tapped "Done" — canonical close
                return True
            # Pump Playwright for a short slice so the CDP screencast keeps
            # delivering frames to the viewer. A dead sleep here froze the live
            # view between polls, so taps landed on stale/refreshed tiles.
            try:
                self.page.wait_for_timeout(self._frame_slice_ms)
            except Exception:
                return False   # page / browser gone
            if self.interactive:
                continue       # edit session: only the human's "Done" (checked above) completes
            # Check periodically (cheaper than per frame).
            now = self._clock()
            if now - last_check >= self.poll_interval_s:
                last_check = now
                # Fast path: the response token was latched (e.g. reCAPTCHA).
                if self._cleared():
                    self._drain_pointers(forward_pointer, vp)
                    return True
                # Captcha-resolve path: the captcha we were solving is GONE and
                # STAYS gone. A consent-popup reload makes it briefly absent then
                # it returns (resetting the timer); only a real advance keeps it
                # gone past the window.
                try:
                    present = classify_gate(self.page) not in ("none", "cleared")
                except Exception:
                    present = True   # navigating / uncertain -> assume present
                if present:
                    if gone_since is not None and _DEBUG:
                        print("[lv] captcha reappeared — resolve timer reset", flush=True)
                    gone_since = None
                else:
                    if gone_since is None:
                        gone_since = now
                        if _DEBUG:
                            print("[lv] captcha absent — starting resolve timer", flush=True)
                    elif now - gone_since >= self._resolve_absence_s:
                        if _DEBUG:
                            print(f"[lv] captcha gone {self._resolve_absence_s}s -> resolved",
                                  flush=True)
                        return True
        return False

    def _cleared(self) -> bool:
        """A gate is cleared when EITHER the response token appears in place
        (e.g. reCAPTCHA checkbox), OR solving it advanced the flow — the form
        submitted and the page navigated past the gate (e.g. an ATS email step).
        Watching only for the in-place token missed the navigation case."""
        # The response token is the ONLY unambiguous proof of a solve. Detect
        # nothing else: URL changes / widget-gone / nav-errors all false-fire on
        # benign things like dismissing a consent popup. The token is latched by
        # the in-page observer into window AND localStorage, so it survives an
        # SPA view-swap or a same-origin navigation.
        try:
            latched = self.page.evaluate(
                "() => (window.__cca_cleared === true)"
                " || (function(){ try { return localStorage.getItem('__cca_cleared') === '1'; }"
                " catch (e) { return false; } })()")
            if latched:
                return True
            if self.is_cleared(self.page):   # fallback: token still in the DOM
                return True
        except Exception:
            return False   # a transient/navigation error is NOT proof of a solve
        return False

    def _drain_pointers(self, forward_pointer, vp, forward_keys=None) -> None:
        while True:
            try:
                nx, ny, kind = self._pointer_q.get_nowait()
            except queue.Empty:
                return
            if kind == "__done__":
                self._human_done = True   # the human pressed "Done" / Submit
                continue
            if kind in ("__text__", "__key__", "__clear__"):   # typed input -> keyboard
                _fk = forward_keys
                if _fk is None:
                    from career_agent.browser.live_view.cdp_bridge import forward_keys as _fk
                try:
                    _fk(self.page, kind, nx)   # nx carries the value (text/key); ny unused
                except Exception:
                    pass
                continue
            if kind == "__scroll__":            # swipe -> wheel scroll (nx carries dy)
                try:
                    from career_agent.browser.live_view.cdp_bridge import forward_scroll
                    forward_scroll(self.page, nx)
                except Exception:
                    pass
                continue
            try:
                forward_pointer(self.page, nx, ny, kind, vp["width"], vp["height"])
                if _DEBUG:
                    print(f"[lv] tap applied ({nx:.3f},{ny:.3f}) {kind}", flush=True)
                if kind == "click" and self._server is not None:
                    # hand the phone the tapped field's current text, so it loads
                    # into the edit box (read + iterate the draft).
                    try:
                        val = self.page.evaluate(
                            "() => { const e=document.activeElement; if(!e) return '';"
                            " if(e.getAttribute && e.getAttribute('role')==='combobox'){"
                            "  const c=e.closest('[class*=control]');"
                            "  const s=c&&c.querySelector('[class*=single-value]');"
                            "  return s?s.textContent.trim():''; }"
                            " return (e.value!==undefined?e.value:'') || ''; }")
                        self._server.push_field_value(val)
                    except Exception:
                        pass
            except Exception as e:
                if _DEBUG:
                    print(f"[lv] tap FAILED: {e!r}", flush=True)
                pass   # a bad tap must never crash the pump

    def close(self) -> None:
        from career_agent.browser.live_view.cdp_bridge import stop_screencast
        if getattr(self, "_token", None) is not None:
            self._token.used = True   # revoke — no reconnects after the session ends
        try:
            if self._cdp is not None:
                stop_screencast(self._cdp)
        finally:
            if self._server is not None:
                self._server.stop()
