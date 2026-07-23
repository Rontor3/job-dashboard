"""Interactive Naukri login -> caches a session for the unattended source.

Run occasionally (session is IP-bound and can expire — see the IP/hosting
notes in vendor/NopeRi/src/client/naukri_client.py; a home/residential IP is
by far the most reliable). Reads credentials from the environment / .env;
NEVER prints, logs, or stores the password.

NopeRi's ``NaukriLoginClient.login()`` has no integrated OTP branch — it
raises a generic ``NaukriAuthError`` on any non-OK login response, with no
way to tell "OTP required" apart from "wrong password" or "blocked IP" from
the exception alone. So on any login failure we fall back to the manual
OTP flow NopeRi exposes (``send_otp()`` then ``verify_otp(code)``) and
prompt for the 6-digit code; if that also fails, both errors are reported
and the account genuinely couldn't authenticate.

    python3 scripts/naukri_login.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "NopeRi"
sys.path.insert(0, str(VENDOR))
SESSION_PATH = ROOT / "data" / "naukri_session.json"


def main():
    user = os.getenv("NAUKRI_USERNAME")
    pw = os.getenv("NAUKRI_PASSWORD")
    if not user or not pw:
        print("Set NAUKRI_USERNAME and NAUKRI_PASSWORD in .env first.")
        return 1

    # Read-only import surface: login/OTP/session only — never apply_job,
    # apply_agent, resume-upload, or profile-update code.
    from src.client.naukri_client import NaukriLoginClient  # type: ignore
    from job_dashboard.sources.naukri_session_shim import (
        force_curl_cffi_backend,
        serialize_session,
    )

    # NopeRi's default session backend is httpcloak (unvendored here); use
    # curl_cffi instead, matching requirements.txt.
    force_curl_cffi_backend()

    client = NaukriLoginClient(user, pw)

    # Any login failure (auth error, blocked IP, transport error) falls back to
    # the manual OTP flow rather than dumping a raw traceback.
    try:
        client.login()
    except Exception as exc:
        print(f"Login did not complete directly ({type(exc).__name__}); trying the OTP flow.")
        # Naukri sends OTP by SMS (mobile) or email depending on the account;
        # the endpoint differs, so ask which channel actually received it.
        channel = input("Where did/should the OTP arrive — [m]obile SMS or [e]mail? ").strip().lower()
        is_mobile = not channel.startswith("e")
        try:
            client.send_otp(is_mobile=is_mobile)
        except Exception as send_exc:
            print(f"Login failed ({type(exc).__name__}); could not trigger an OTP "
                  f"either ({type(send_exc).__name__}). Check credentials / IP and retry.")
            return 1
        code = input("Enter the OTP Naukri sent you: ").strip()
        try:
            client.verify_otp(code, is_mobile=is_mobile)
        except Exception as otp_exc:
            print(f"OTP verification failed ({type(otp_exc).__name__}).")
            return 1

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(serialize_session(client)))
    print(f"Naukri session cached to {SESSION_PATH}. Refreshes will now include Naukri.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
