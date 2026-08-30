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
    s1 = [_f("#n", "Full name", "full_name"), _f("#c", "Submit application", None, kind="button")]
    deps = Deps([s1])
    calls = {"n": 0}
    def prep_fn(page): calls["n"] += 1
    walk(object(), CandidateProfile(contact={"full_name": "R"}), Human(), deps,
         do_submit=True, autonomous=True, prep_fn=prep_fn)
    assert calls["n"] >= 1


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


def test_learn_records_then_recalls_across_walks():
    # First walk: human answers a novel question. Second walk (same question,
    # varied wording): the learned answer is reused, human.collect never fires.
    import sqlite3
    from career_agent.memory.learned_answers import AnswerMemory
    mem = AnswerMemory(sqlite3.connect(":memory:"))
    prof = CandidateProfile(contact={})

    q1 = [_f("#np", "Notice period (in days)", None, required=True),
          _f("#c", "Submit application", None, kind="button")]
    walk(object(), prof, Human(), Deps([q1]), do_submit=True, autonomous=True, learn=mem)

    seen = {}
    class H(Human):
        def collect(self, fields): seen["called"] = True; return {f.ref: "X" for f in fields}
    q2 = [_f("#np2", "Notice Period (In Days)", None, required=True),
          _f("#c", "Submit application", None, kind="button")]
    deps2 = Deps([q2])
    walk(object(), prof, H(), deps2, do_submit=True, autonomous=True, learn=mem)
    filled = [d for batch in deps2.filled for d in batch]
    assert any(d.ref == "#np2" and d.value == "X" and d.source == "learned" for d in filled)
    assert "called" not in seen            # reused -> human never asked again


def test_recall_overrides_a_wrong_rule_fill():
    # a learned CORRECTION for a field must win over what the rules would fill.
    import sqlite3
    from career_agent.memory.learned_answers import AnswerMemory
    mem = AnswerMemory(sqlite3.connect(":memory:"))
    # human once corrected "Phone" to a specific value -> recorded
    mem.record(_f("#p", "Phone", "phone"), "+91 99999 88888")
    prof = CandidateProfile(contact={"phone": "+91 00000 00000"})   # rule would fill this
    s1 = [_f("#p", "Phone", "phone"), _f("#c", "Submit application", None, kind="button")]
    deps = Deps([s1])
    walk(object(), prof, Human(), deps, do_submit=True, autonomous=True, learn=mem)
    filled = [d for batch in deps.filled for d in batch]
    phone = next(d for d in filled if d.ref == "#p")
    assert phone.value == "+91 99999 88888"       # recall (correction) beat the rule
    assert phone.source == "learned"


def test_walk_learns_corrections_at_submit():
    # agent fills; human edits the live form; at submit the walk diffs read-back
    # vs what it filled and learns the change.
    import sqlite3
    from career_agent.memory.learned_answers import AnswerMemory
    mem = AnswerMemory(sqlite3.connect(":memory:"))
    prof = CandidateProfile(contact={"phone": "+91 000"})

    class DepsRB(Deps):
        def read_back(self, page, decisions):
            return {"#p": "+91 99999"}      # human corrected the phone on the live form

    s1 = [_f("#p", "Phone", "phone"), _f("#s", "Submit application", None, kind="button")]
    walk(object(), prof, Human(), DepsRB([s1]), do_submit=True, autonomous=True, learn=mem)
    # next form: recall now serves the human's correction
    dec, _ = mem.recall([_f("#p2", "Phone", "phone")])
    assert dec and dec[0].value == "+91 99999"
