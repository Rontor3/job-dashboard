"""OTP via the connected human instead of a silent half-hour (class C, live
2026-10-20: the credential provider polled Gmail for 1800 s; eight queued jobs
timed out with nothing learned). Attended run: ONE short ask to the human
channel, park with reason otp_unanswered on silence, queue re-drains later.
Headless keeps the old 1800 s poll. Offline: fake collectors, injected waits."""
import career_agent.browser.credential_provider as cp
import career_agent.integrations.gmail_otp as gmail


class _FakeCollector:
    def __init__(self, answers=None, waits=()):
        self.answers = answers or {}
        self.calls = []
        self.deadlines = {}          # (deadline_s, text_deadline_s) seen during the call
        self.deadline_s, self.text_deadline_s = 900, 1800
        self._waits_saved = waits
    def __call__(self, fields):
        self.calls.append(fields)
        self.deadlines["during"] = (self.deadline_s, self.text_deadline_s)
        return dict(self.answers)
    def after(self):
        self.deadlines["after"] = (self.deadline_s, self.text_deadline_s)


def _ask(monkeypatch, collector, code_recorder):
    monkeypatch.setattr(cp, "_apply_otp_code", lambda page, code, cred, site: code_recorder.append(code))
    monkeypatch.setattr(cp, "_ASK", {"collector": collector})



def test_an_answer_proceeds_and_never_parks(monkeypatch):
    seen = []
    col = _FakeCollector({"otp_code": "123456"})
    _ask(monkeypatch, col, seen)
    cp._handle_otp_state(None, "acme.com", {})           # page unused: verify handled by the fake
    assert seen == ["123456"]                            # one answer -> straight to the code use
    assert cp._PARK["reason"] is None
    assert len(col.calls) == 1                           # exactly ONE ask


def test_silence_parks_the_run_with_a_named_reason(monkeypatch, capsys):
    seen = []
    col = _FakeCollector({})                              # the human stayed silent
    _ask(monkeypatch, col, seen)
    cp._handle_otp_state(None, "acme.com", {})
    assert seen == [] and cp._PARK["reason"] == "otp_unanswered"
    assert "otp_unanswered" in capsys.readouterr().out
    assert len(col.calls) == 1                            # one short ask, never an 1800 s poll


def test_the_ask_window_is_shrunk_then_restored(monkeypatch):
    seen, col = [], _FakeCollector({})
    _ask(monkeypatch, col, seen)
    cp._handle_otp_state(None, "acme.com", {})
    col.after()
    assert col.deadlines["during"] == (120, 120)          # ≤ _OTP_ASK_S while the human was asked
    assert col.deadlines["after"] == (900, 1800)          # the collector's own waits restored


def test_a_pasted_magic_link_flows_through_unchanged(monkeypatch):
    seen, col = [], _FakeCollector({"otp_code": "https://acme.com/verify?u=x"})
    _ask(monkeypatch, col, seen)
    cp._handle_otp_state(None, "acme.com", {})
    assert seen == ["https://acme.com/verify?u=x"]


def test_headless_still_polls_gmail_for_the_full_window(monkeypatch):
    seen, polls = [], {}
    _ask(monkeypatch, None, seen)
    monkeypatch.setattr(gmail, "available", lambda: True)
    def _poll(**k):
        polls.update(k)
        return "654321"
    monkeypatch.setattr(gmail, "poll_otp", _poll)
    with monkeypatch.context() as m:
        m.setattr(cp, "_RUN_START", __import__("time").time())
        cp._handle_otp_state(None, "acme.com", {})
    assert polls["timeout_s"] == 1800                     # unchanged fallback semantics
    assert seen == ["654321"]


def test_the_otp_ask_reports_the_field_to_the_human_channel(monkeypatch):
    seen, col = [], _FakeCollector({})
    _ask(monkeypatch, col, seen)
    cp._handle_otp_state(None, "acme-corp.com", {})
    (fields,) = col.calls
    assert fields[0].ref == "otp_code" and fields[0].required
    assert "acme-corp.com" in fields[0].label


def test_park_reason_rides_out_as_the_provider_action(monkeypatch):
    def _attempt(page, gate, site, original_url, email, phone, retried):
        cp._otp_unanswered("acme.com")                    # what a silent OTP handler does
        return False, "login"                             # the wall was not cleared
    monkeypatch.setattr(cp, "_provide_attempt", _attempt)
    ok, action = cp.provide(page=object(), gate="password", site="acme.com", collector=object())
    assert (ok, action) == (False, "otp_unanswered")      # the queue re-drains on this name
    assert cp._ASK["collector"] is None                   # the ask channel never leaks between runs
