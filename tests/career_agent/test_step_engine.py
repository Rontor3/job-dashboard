from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.step_engine import walk


class Deps:
    def __init__(self, screens):
        self._screens = screens; self.filled = []; self.clicks = []; self._i = 0
    def snapshot(self, page): return self._screens[min(self._i, len(self._screens)-1)]
    def gate(self, page): return "none"
    def fill(self, page, decisions): self.filled.append(decisions)
    def click(self, page, label): self.clicks.append(label); self._i += 1
    def url(self, page): return f"http://x/step{self._i}"


class Human:
    def approve(self, card): return True
    def remote_solve(self, page, gate, on_link): return True
    def collect(self, fields): return {f.ref: "X" for f in fields}


def _f(ref, label, purpose=None, required=False, kind="text"):
    return Field(ref, kind, label, required, [], None, purpose)


def test_resume_pdf_threads_to_upload_decision():
    s1 = [_f("#cv", "Attach resume", "resume_upload", kind="file"),
          _f("#c", "Submit application", None, kind="button")]
    deps = Deps([s1])
    walk(object(), CandidateProfile(), Human(), deps, do_submit=True, autonomous=True,
         resume_pdf="/tmp/cv.pdf")
    uploads = [d for batch in deps.filled for d in batch if d.action == "upload"]
    assert uploads and uploads[0].value == "/tmp/cv.pdf"


def test_walks_two_screens_then_submits():
    s1 = [_f("#n", "Full name", "full_name"), _f("#c", "Continue", None, kind="button")]
    s2 = [_f("#s", "Submit application", None, kind="button")]
    deps = Deps([s1, s2])
    prof = CandidateProfile(contact={"full_name": "R"})
    out = walk(object(), prof, Human(), deps, do_submit=True, autonomous=True)
    assert out["screens"] >= 2
    assert "Continue" in deps.clicks
    assert out["submitted"] is True


def test_stops_on_unrecoverable_gate():
    class G(Deps):
        def gate(self, page): return "cloudflare_interstitial"
    out = walk(object(), CandidateProfile(), Human(), G([[_f("#a", "A")]]))
    assert out["submitted"] is False and out["stopped_reason"].startswith("gate:")


def test_stops_on_otp_email_gate():
    # otp_email routes to its own handler (not "escalate"); the walk must still
    # stop on it — Gmail-OTP auto-read is a later sub-project, never bypass now.
    class G(Deps):
        def gate(self, page): return "otp_email"
    form = [_f("#code", "Verification code"), _f("#c", "Continue", None, kind="button")]
    out = walk(object(), CandidateProfile(), Human(), G([form]), do_submit=True, autonomous=True)
    assert out["submitted"] is False
    assert out["stopped_reason"] == "gate:otp_email"


def test_dry_run_stops_at_submit_without_submitting():
    s1 = [_f("#s", "Submit application", None, kind="button")]
    out = walk(object(), CandidateProfile(), Human(), Deps([s1]), do_submit=False)
    assert out["submitted"] is False
    assert out["stopped_reason"] == "reached_submit_dry_run"
