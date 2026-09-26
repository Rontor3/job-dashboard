from career_agent.integrations.gmail_otp import _extract_code


def test_extract_code_prefers_verify_link():
    body = "Click here: https://x.com/verify?token=abc123 to confirm your email."
    assert _extract_code(body) == "https://x.com/verify?token=abc123"


def test_extract_code_matches_reset_password_link():
    body = "We received a request to reset your password. https://fractal.wd1.myworkdayjobs.com/resetPassword?token=xyz Ignore if not you."
    assert _extract_code(body) == "https://fractal.wd1.myworkdayjobs.com/resetPassword?token=xyz"


def test_extract_code_falls_back_to_numeric_otp():
    body = "Your one-time code is 483920. It expires in 10 minutes."
    assert _extract_code(body) == "483920"


def test_extract_code_none_when_nothing_matches():
    assert _extract_code("Thanks for signing up!") is None
