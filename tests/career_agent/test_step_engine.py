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


def test_walk_runs_prep_fn_each_step():
    s1 = [_f("#n", "Full name", "full_name"), _f("#c", "Continue", None, kind="button")]
    s2 = [_f("#s", "Submit application", None, kind="button")]
    order = []

    class D(Deps):
        def snapshot(self, page):
            order.append("snapshot")
            return super().snapshot(page)

    walk(object(), CandidateProfile(contact={"full_name": "R"}), Human(), D([s1, s2]),
         do_submit=True, autonomous=True, prep_fn=lambda page: order.append("prep"))
    starts = [i for i, o in enumerate(order) if o == "prep"]
    assert len(starts) == 2
    assert all(order[i + 1] == "snapshot" for i in starts)


def test_walk_uses_judge_fn_before_human_collect():
    s1 = [_f("#q", "Why us?", None, required=True, kind="textarea"),
          _f("#c", "Submit application", None, kind="button")]
    deps = Deps([s1])
    prof = CandidateProfile(contact={})
    seen = {}
    class H(Human):
        def collect(self, fields): seen["refs"] = [f.ref for f in fields]; return {}
    def judge_fn(needs):
        from career_agent.orchestrator.mapper import FillDecision
        return ([FillDecision("#q", "textarea", "Why us?", "Because ML.", "fill", "judgment")], [], set())
    walk(object(), prof, H(), deps, do_submit=True, autonomous=True, judge_fn=judge_fn)
    filled = [d for batch in deps.filled for d in batch]
    assert any(d.ref == "#q" and d.source == "judgment" for d in filled)
    assert "refs" not in seen              # judge answered all -> human.collect never called


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
    assert out["screens"] == 2
    assert deps.clicks == ["Continue", "Submit application"]
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
    deps = Deps([s1])
    out = walk(object(), CandidateProfile(), Human(), deps, do_submit=False)
    assert out["submitted"] is False
    assert out["stopped_reason"] == "reached_submit_dry_run"
    assert deps.clicks == []


def test_learn_records_then_recalls_across_walks(qbank_conn, fake_embed):
    # A question answered once on the Answers tab is filled from the bank on a
    # later walk (varied wording): human.collect never fires.
    from career_agent.memory.qbank_memory import QBankMemory
    mem = QBankMemory(qbank_conn, embed=fake_embed)
    seen = {}
    class H(Human):
        def collect(self, fields): seen["called"] = True; return {f.ref: "X" for f in fields}
    q = [_f("#np", "Notice Period", None, required=True),
         _f("#c", "Submit application", None, kind="button")]
    deps = Deps([q])
    walk(object(), CandidateProfile(contact={}), H(), deps, do_submit=True, autonomous=True, learn=mem)
    filled = [d for batch in deps.filled for d in batch]
    assert any(d.ref == "#np" and d.value == "30" and d.source == "qbank" for d in filled)
    assert "called" not in seen


def test_recall_overrides_a_wrong_rule_fill(qbank_conn, fake_embed):
    # the bank's answer for a field must win over what the rules would fill.
    from career_agent.memory.qbank_memory import QBankMemory
    mem = QBankMemory(qbank_conn, embed=fake_embed)
    prof = CandidateProfile(contact={"linkedin_url": "linkedin.com/in/stale"})   # rule would fill this
    s1 = [_f("#l", "LinkedIn profile URL", "linkedin_url"), _f("#c", "Submit application", None, kind="button")]
    deps = Deps([s1])
    walk(object(), prof, Human(), deps, do_submit=True, autonomous=True, learn=mem)
    filled = [d for batch in deps.filled for d in batch]
    link = next(d for d in filled if d.ref == "#l")
    assert link.value == "linkedin.com/in/x" and link.source.startswith("qbank")
