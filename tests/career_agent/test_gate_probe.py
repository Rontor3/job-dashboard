from career_agent.browser.gate_probe import classify_from_signals, HANDLERS, GATES


def _sig(**kw):
    base = dict(recaptcha_iframe=False, grecaptcha_response_present=False,
                recaptcha_bframe_visible=False, hcaptcha_iframe=False,
                hcaptcha_challenge_visible=False, turnstile_iframe=False,
                cf_interstitial=False, otp_email_field=False, otp_sms_field=False)
    base.update(kw)
    return base


def test_none_when_no_signals():
    assert classify_from_signals(_sig()) == "none"


def test_cloudflare_interstitial():
    assert classify_from_signals(_sig(cf_interstitial=True)) == "cloudflare_interstitial"


def test_recaptcha_v2_image_when_challenge_open():
    assert classify_from_signals(
        _sig(recaptcha_iframe=True, recaptcha_bframe_visible=True)
    ) == "recaptcha_v2_image"


def test_recaptcha_v2_checkbox_present_not_open():
    assert classify_from_signals(_sig(recaptcha_iframe=True)) == "recaptcha_v2_checkbox"


def test_recaptcha_cleared_when_token_present():
    assert classify_from_signals(
        _sig(recaptcha_iframe=True, grecaptcha_response_present=True)
    ) == "cleared"


def test_turnstile_and_otp():
    assert classify_from_signals(_sig(turnstile_iframe=True)) == "turnstile"
    assert classify_from_signals(_sig(otp_email_field=True)) == "otp_email"


def test_every_gate_has_a_handler():
    for g in GATES:
        assert g in HANDLERS
    assert HANDLERS["cloudflare_interstitial"] == "escalate"
    assert HANDLERS["recaptcha_v2_checkbox"] == "escalate"
    assert HANDLERS["turnstile"] == "proceed"
    assert HANDLERS["otp_email"] == "otp_email"
