from career_agent.browser.gate_probe import is_cleared_from_signals


def test_cleared_when_recaptcha_token_present():
    assert is_cleared_from_signals({"grecaptcha_response_present": True}) is True


def test_cleared_when_hcaptcha_token_present():
    assert is_cleared_from_signals({"hcaptcha_response_present": True}) is True


def test_not_cleared_when_absent():
    assert is_cleared_from_signals({}) is False
