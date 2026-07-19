"""Session serialize/restore shim for the vendored NopeRi NaukriLoginClient.

NopeRi's ``NaukriLoginClient`` (vendor/NopeRi/src/client/naukri_client.py) has
no built-in way to reconstruct a session without a fresh login. This module
adds that missing piece so the read-only Naukri source
(``naukri_source.py``) can run unattended off a session cached to disk by
``scripts/naukri_login.py``.

Read-only by construction: this module only ever touches
``NaukriLoginClient.session`` / ``.naukri_session`` (the HTTP session object
+ bearer token). It never imports or invokes ``apply_job``, resume-upload,
or profile-update code.

Verified against the vendored source (git clone of
https://github.com/Traverser25/NopeRi):

  - naukri_client.py:145 ``self.naukri_session = NaukriSession(token,
    self.session.cookies)`` -> models.py:7-11 ``NaukriSession(bearer_token,
    cookies, login_time)``. The real token attribute is
    ``.naukri_session.bearer_token`` -- NOT ``self.token`` as an early draft
    guessed.
  - naukri_client.py:115 ``headers["authorization"] = f"Bearer
    {self.naukri_session.bearer_token}"`` confirms the same attribute.
  - naukri_client.py:105 ``self.session = build_session()`` ->
    session.py:5-14: the *default* backend is ``httpcloak``
    (``USE_CURL_CFFI = False``); ``curl_cffi`` is only used if that
    module-level flag is flipped. This project's requirements.txt only
    vendors ``curl_cffi`` (not ``httpcloak``, which NopeRi's own
    requirements.txt separately pins), so ``force_curl_cffi_backend()``
    flips the flag at runtime rather than editing the vendored file --
    keeps a fresh ``git clone --depth 1`` re-vendor safe/idempotent.
  - ``curl_cffi.requests.cookies.Cookies`` is a ``MutableMapping``:
    ``dict(session.cookies)`` and ``session.cookies.update(...)`` both work
    with no network I/O (verified locally against curl_cffi).
  - NopeRi's ``login()`` has NO integrated OTP branch: it raises
    ``NaukriAuthError("Login failed")`` generically on any non-OK login
    response, with no way to distinguish "OTP required" from "wrong
    password" or "blocked IP" in the exception itself. OTP is a fully
    separate, manually-orchestrated pair of calls: ``send_otp()`` then
    ``verify_otp(code)`` (naukri_client.py:222-263 and :161-219).
    ``scripts/naukri_login.py`` drives that manually on login failure
    rather than relying on an OTP-flavoured exception message.
"""
import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[3] / "vendor" / "NopeRi"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from src.client.naukri_client import NaukriLoginClient  # type: ignore
from src.client.session import build_session  # type: ignore
from src.models.models import NaukriSession  # type: ignore
import src.client.session as _session_mod  # type: ignore


def force_curl_cffi_backend():
    """Make ``build_session()`` return a curl_cffi session instead of the
    default (and unvendored) httpcloak one.

    Only flips the module-level flag read by ``build_session()`` at call
    time -- does not edit the vendored file, so re-cloning NopeRi never
    silently reverts this.
    """
    _session_mod.USE_CURL_CFFI = True


def serialize_session(login_client) -> dict:
    """Token + cookies only -- never username/password.

    Call right after a real interactive login/OTP-verify
    (``scripts/naukri_login.py``); writes exactly what ``restore_session``
    below needs to reconstruct a usable client with no network call.
    """
    return {
        "token": login_client.naukri_session.bearer_token,
        "cookies": dict(login_client.session.cookies),
    }


def restore_session(login_client, data: dict):
    """Set token + cookies on a bare instance. No network call.

    Bound onto ``NaukriLoginClient`` below, so callers may use either the
    free-function form ``restore_session(login_client, data)`` or the bound
    form ``login_client.restore_session(data)`` (the form
    ``naukri_source.py`` uses, since it builds the instance via
    ``NaukriLoginClient.__new__`` -- bypassing ``__init__`` entirely, so
    ``login_client.session`` does not exist yet when this runs).
    """
    if getattr(login_client, "session", None) is None:
        force_curl_cffi_backend()
        login_client.session = build_session()  # object construction only, no I/O
    login_client.session.cookies.update(data["cookies"])
    login_client.naukri_session = NaukriSession(
        bearer_token=data["token"], cookies=data["cookies"]
    )
    login_client.profile_id = None
    login_client.cache = {}


NaukriLoginClient.restore_session = restore_session
