import json
from dataclasses import dataclass
from job_dashboard.apply import naukri_resume


@dataclass
class FakeUpdateResult:
    profile_id: str
    raw_response: dict
    status_code: int


class FakeClient:
    """Mimics NopeRi's NaukriLoginClient surface used by push_resume.
    `body` is the update response — set it to echo the filename or not."""
    def __init__(self, status=200, body=None, raise_on_update=False):
        self._status = status
        self._body = {} if body is None else body
        self._raise = raise_on_update
    def update_resume(self, pdf_path):
        if self._raise:
            raise RuntimeError("token expired")
        return FakeUpdateResult("pid1", self._body, self._status)


def _session(tmp_path):
    p = tmp_path / "naukri_session.json"
    p.write_text(json.dumps({"token": "t", "cookies": {}}))
    return p


def test_push_ok_and_body_echoes_filename(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/rakshit_ml.pdf", session_path=sp, settle_seconds=0,
        client_factory=lambda s: FakeClient(
            status=200, body={"resume": {"fileName": "rakshit_ml.pdf"}}))
    assert r.ok is True
    assert r.live_resume_name == "rakshit_ml.pdf"  # confirmed from body
    assert r.error is None


def test_push_ok_but_name_unconfirmable(tmp_path):
    # 2xx accepted, but the body does not echo the filename -> still ok, name None.
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/rakshit_ml.pdf", session_path=sp, settle_seconds=0,
        client_factory=lambda s: FakeClient(status=200, body={"formKey": "f"}))
    assert r.ok is True and r.error is None
    assert r.live_resume_name is None


def test_upload_rejected_on_non_2xx(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=sp, settle_seconds=0,
        client_factory=lambda s: FakeClient(status=406))
    assert r.ok is False and r.error == "upload_rejected"


def test_no_session_file_short_circuits(tmp_path):
    calls = []
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=tmp_path / "missing.json", settle_seconds=0,
        client_factory=lambda s: calls.append(1))
    assert r.ok is False and r.error == "no_session"
    assert calls == []  # factory never called


def test_client_exception_is_caught(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=sp, settle_seconds=0,
        client_factory=lambda s: FakeClient(raise_on_update=True))
    assert r.ok is False and r.error == "RuntimeError"


def test_verify_false_skips_readback(tmp_path):
    sp = _session(tmp_path)
    r = naukri_resume.push_resume(
        "/tmp/x.pdf", session_path=sp, verify=False, settle_seconds=0,
        client_factory=lambda s: FakeClient(status=200, body={}))
    assert r.ok is True and r.error is None
