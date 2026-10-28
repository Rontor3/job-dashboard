"""wall_reason: the wall left standing must be NAMED, not a bare 'auth_wall'.

Live 2026-10-27: IBM SSO took email+password then asked for a code the run never saw
(mfa_required); Mahindra's SuccessFactors register sat 100% filled behind reCAPTCHA v2
(captcha_required); Darwinbox's primeserv served error-page/not-allowed; MathWorks showed
a 'Select a Web Site' geo-modal nobody clicked. Seven different failures, one label."""
from src.career_agent.browser.credential_provider import _truly_visible, wall_reason


class FakeEl:
    def __init__(self, visible=True, box=None):
        self._visible, self._box = visible, box or {"width": 300, "height": 80}

    def is_visible(self):
        return self._visible

    def bounding_box(self):
        return self._box

    def evaluate(self, js, arg=None):
        return self._visible


class FakePage:
    def __init__(self, text="", url="https://employer.example/auth/login", otp=None, captcha=()):
        self._text, self.url, self._otp, self._captcha = text, url, otp, list(captcha)

    def inner_text(self, _sel):
        return self._text

    def query_selector(self, _sel):
        return self._otp

    def query_selector_all(self, _sel):
        return self._captcha


def test_geo_interstitial_mathworks():
    assert wall_reason(FakePage(text="Select a Web Site to continue. North America / Worldwide")) == "geo_interstitial"


def test_not_allowed_primeserv():
    assert wall_reason(FakePage(url="https://prime.error-page/not-allowed")) == "not_allowed"


def test_captcha_by_text_and_by_widget():
    assert wall_reason(FakePage(text="Please complete the captcha to continue")) == "captcha_required"
    # an invisible v3 badge must NOT count
    assert wall_reason(FakePage(captcha=[FakeEl(visible=False)])) == "auth_wall"
    # a real checkbox-sized widget does
    assert wall_reason(FakePage(captcha=[FakeEl(visible=True)])) == "captcha_required"


def test_mfa_before_wrong_password_words():
    # 'Invalid code' contains an _LOGIN_ERROR word — mfa must win (IBM SSO, live 2026-10-27)
    assert wall_reason(FakePage(text="Invalid verification code", otp=FakeEl())) == "mfa_required"


def test_wrong_password_by_words():
    assert wall_reason(FakePage(text="The email address or password is incorrect")) == "wrong_password"


def test_fallback_is_plain_auth_wall():
    assert wall_reason(FakePage(text="Welcome to the careers portal")) == "auth_wall"


def test_overlay_hidden_password_is_not_visible():
    # is_visible() true but the hit-test says an overlay covers it → _truly_visible False
    class OverlayEl:
        def is_visible(self):
            return True

        def evaluate(self, js, arg=None):
            return False  # elementFromPoint hit the backdrop, not the field

    assert _truly_visible(OverlayEl()) is False
    assert _truly_visible(FakeEl(visible=True)) is True
    assert _truly_visible(FakeEl(visible=False)) is False
