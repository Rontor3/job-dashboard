"""Gate probe — DETECTS verification gates, never solves them.

`classify_from_signals` is pure. `classify_gate` gathers the signals from a
live page. HANDLERS routes each gate to a string action; every genuine
challenge ships `escalate`. Nothing here interacts with a challenge widget,
and nothing imports any bypass/solver/proxy tool."""
from __future__ import annotations

GATES = frozenset({
    "recaptcha_v2_checkbox", "recaptcha_v2_image", "recaptcha_v3",
    "hcaptcha_checkbox", "hcaptcha_image", "turnstile",
    "cloudflare_interstitial", "otp_email", "otp_sms",
    "text_challenge", "cleared", "none",
})

# Detection routing only. `escalate` = hand to a human (Phase 1: stop + report).
HANDLERS: dict[str, str] = {g: "escalate" for g in GATES}
HANDLERS.update({
    "none": "proceed", "cleared": "proceed",
    "recaptcha_v3": "proceed", "turnstile": "proceed",
    "otp_email": "otp_email",
})


def classify_from_signals(sig: dict) -> str:
    # cleared beats "present" — a solved reCAPTCHA/hCaptcha writes a response
    # token, so the gate is done even though its iframe is still in the DOM.
    if sig.get("grecaptcha_response_present") or sig.get("hcaptcha_response_present"):
        return "cleared"
    if sig.get("cf_interstitial"):
        return "cloudflare_interstitial"
    if sig.get("hcaptcha_iframe"):
        return "hcaptcha_image" if sig.get("hcaptcha_challenge_visible") else "hcaptcha_checkbox"
    if sig.get("recaptcha_iframe"):
        return "recaptcha_v2_image" if sig.get("recaptcha_bframe_visible") else "recaptcha_v2_checkbox"
    if sig.get("turnstile_iframe"):
        return "turnstile"
    if sig.get("otp_email_field"):
        return "otp_email"
    if sig.get("otp_sms_field"):
        return "otp_sms"
    return "none"


def _gather_signals(page) -> dict:
    js = r"""
    () => {
      const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect();
        return r.width > 10 && r.height > 10; };
      const q = (s) => document.querySelector(s);
      const token = q('textarea#g-recaptcha-response');
      return {
        recaptcha_iframe: !!q('iframe[src*="recaptcha/api2/anchor"]'),
        grecaptcha_response_present: !!(token && token.value && token.value.length > 0),
        recaptcha_bframe_visible: vis(q('iframe[src*="recaptcha/api2/bframe"]')),
        hcaptcha_iframe: !!q('iframe[src*="hcaptcha.com"]'),
        hcaptcha_challenge_visible: vis(q('iframe[src*="hcaptcha.com/captcha"]')),
        hcaptcha_response_present: (() => { const t = q('textarea[name="h-captcha-response"]');
          return !!(t && t.value && t.value.length > 0); })(),
        turnstile_iframe: !!q('iframe[src*="challenges.cloudflare.com"]'),
        cf_interstitial: /just a moment|checking your browser/i.test(document.title || ''),
        otp_email_field: !!q('input[autocomplete="one-time-code"], input:not([type="hidden"])[name*="otp" i], input:not([type="hidden"])[name*="verification" i]'),
        otp_sms_field: false,
      };
    }
    """
    return page.evaluate(js)


def classify_gate(page) -> str:
    return classify_from_signals(_gather_signals(page))


def is_cleared_from_signals(sig: dict) -> bool:
    return bool(sig.get("grecaptcha_response_present")
                or sig.get("hcaptcha_response_present"))


def is_cleared(page) -> bool:
    """Live-page check used by remote solve to detect the human's solve: a
    response token has appeared (or no gate remains)."""
    return is_cleared_from_signals(_gather_signals(page))


def is_cleared_for(gate: str):
    """Return a gate-specific cleared-check. On a page carrying BOTH captchas,
    keying on 'either token' false-clears (an auto reCAPTCHA token latches while
    the hCaptcha is still unsolved), so an hcaptcha_* gate checks only the
    hCaptcha token, a recaptcha_* gate only the reCAPTCHA token."""
    g = str(gate or "")
    if g.startswith("hcaptcha"):
        return lambda page: bool(_gather_signals(page).get("hcaptcha_response_present"))
    if g.startswith("recaptcha"):
        return lambda page: bool(_gather_signals(page).get("grecaptcha_response_present"))
    return is_cleared
