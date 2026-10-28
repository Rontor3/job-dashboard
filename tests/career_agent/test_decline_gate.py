"""The decline gate: marketing-acquisition asks are answered by policy, not by
the LLM judge or a human — and their required variants are held, never stuffed
with a decline (qbank_memory's invariant, in policy form). See
docs/career-agent/triage/answer-pipeline-analysis.md §4 Candidate C and
answer-redteam.md §C-1/C-2/C-3 for the corrections this file encodes."""
from __future__ import annotations

import sqlite3

import pytest

from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator import decline_class as dc
from career_agent.orchestrator.answering import answer_fields
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.qa_recorder import QARecorder
from job_dashboard import autonomy, qa_store

P = CandidateProfile(contact={})


def _f(ref, label, kind="checkbox", required=False, options=None, purpose=None, description=""):
    return Field(ref, kind, label, required, options or [], None, purpose, description)


def _ctx(conn, job_id=7, run_key="run", judge=None, profile=P):
    return {"profile": profile, "qa": QARecorder(conn, job_id, run_key=run_key),
            **({"judge_fn": judge} if judge else {})}


def _db(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")
    qa_store.ensure(conn)
    return conn


def _row(conn, run_key, ref):
    r = conn.execute("SELECT label, answer, source, status, basis, kind FROM application_qa "
                     "WHERE run_key=? AND ref=?", (run_key, ref)).fetchone()
    return dict(zip(["label", "answer", "source", "status", "basis", "kind"], r))


def _recording_judge():
    """judge_fn stand-in: records the fields it was asked about, escalates them."""
    seen = []

    def judge(fields):
        seen.extend(f.ref for f in fields)
        return [], list(fields), set()
    return judge, seen


# ── the classifier, table style ──────────────────────────────────────────────

def test_the_30604_label_is_declined_at_the_event():
    # experiment: the bank's nearest candidates scored 0.42-0.51, below floor — the gate is the rung
    v = dc.classify(_f("#m", "Get email updates for the latest senior data scientist jobs"))
    assert (v.action, v.pattern) == (dc.DECLINE, "get-email-updates")


@pytest.mark.parametrize("label,kind,required,options", [
    ("Get email updates for the latest data scientist jobs in bengaluru, karnataka", "checkbox", False, []),
    ("Join our jobs newsletter", "checkbox", False, []),
    ("I agree to receive marketing communications", "checkbox", False, []),
    ("I agree to receive updates about new job opportunities", "checkbox", False, []),
    ("By checking this box, I consent to receive transactional and marketing email "
     "messages regarding employment opportunities and know I can unsubscribe at any time", "checkbox", False, []),
    ("I agree to receive job alerts on WhatsApp", "checkbox", False, []),
    ("Hear more about career opportunities, events and company news", "checkbox", False, []),
    ("Follow ACME to stay up to date with news and opportunities", "checkbox", False, []),
    ("Join our talent community", "checkbox", False, []),
    ("Would you like to receive job alerts?", "radio_group", False, ["Yes", "No"]),
    ("Get job alerts", "select", False, ["Yes", "No"]),
])
def test_marketing_phrasings_decline(label, kind, required, options):
    assert dc.classify(_f("#x", label, kind, required, options)).action == dc.DECLINE


@pytest.mark.parametrize("label,kind,required,options", [
    # Gulf/Workday consent-to-contact and the like are application asks (C-1) — never declined
    ("Please notify me of the status of my application via email / SMS", "checkbox", True, []),
    ("Please notify me of the status of my application via email", "checkbox", False, []),
    ("Please choose your notification language *", "select", True, ["English", "Hindi"]),
    ("Any offer in hand?*", "combobox", True, []),
    ("Would you like to receive SMS messages from Koch and its affiliates regarding "
     "your application and other career opportunities", "radio_group", False, ["Yes", "No"]),
    # profiling opt-ins: the profile may legitimately want the tick
    ("Check here if you're open to relocating — we'll update your profile so companies can contact you", "checkbox", False, []),
    # only shares words with the old regex
    ("Any updates on your availability?", "text", False, []),
    ("Receive monthly tech-tips", "checkbox", False, []),   # a human answer is a fact, not marketing
])
def test_process_and_non_recruitment_asks_are_not_marketing(label, kind, required, options):
    assert dc.classify(_f("#x", label, kind, required, options)).action == dc.ASK


def test_a_required_marketing_ask_is_a_skip_not_a_decline():
    v = dc.classify(_f("#x", "I consent to receive update messages by email", required=True))
    assert v.action == dc.SKIP and "required" in v.reason


def test_decline_value_per_kind_and_the_unrefusable_widget():
    assert dc.decline_value(_f("#c", "Get email updates")) == ("uncheck", False)
    assert dc.decline_value(_f("#r", "Get job alerts", "radio_group", False, ["Yes", "No"])) == ("check_group", "No")
    assert dc.decline_value(_f("#s", "Get job alerts", "select", False, ["Yes", "No"])) == ("select", "No")
    # no option means No -> no fabricated value; an empty-options combobox likewise
    assert dc.decline_value(_f("#r", "Get job alerts", "radio_group", False, ["Opt in", "Opt out"])) is None
    assert dc.decline_value(_f("#cb", "Get email updates", "combobox")) is None


# ── the gate inside answer_fields ────────────────────────────────────────────

def test_optional_marketing_checkbox_is_declined_and_never_asked(tmp_path):
    conn = _db(tmp_path)
    judge, seen = _recording_judge()
    fields = [_f("#m", "Get email updates for the latest senior data scientist jobs")]
    decisions, needs = answer_fields(fields, _ctx(conn, judge=judge))
    assert [(d.ref, d.action, d.value, d.source) for d in decisions] == [("#m", "uncheck", False, dc.SOURCE)]
    assert seen == [] and needs == []                       # never a question for the judge or a human
    row = _row(conn, "run", "#m")
    assert row["source"] == dc.SOURCE and row["status"] == "filled"
    assert "marketing opt-in auto-declined by policy" in row["basis"]


def test_optional_marketing_radio_group_gets_the_no_option(tmp_path):
    conn = _db(tmp_path)
    decisions, needs = answer_fields(
        [_f("#r", "Would you like to receive job alerts?", "radio_group", False, ["Yes", "No"]),
         _f("#s", "Get job alerts", "select", False, ["Yes", "No"])], _ctx(conn))
    by = {d.ref: d for d in decisions}
    assert by["#r"].value == "No" and by["#r"].action == "check_group" and by["#r"].source == dc.SOURCE
    assert by["#s"].value == "No" and by["#s"].action == "select" and by["#s"].source == dc.SOURCE
    assert needs == []


def test_required_marketing_checkbox_is_held_not_stuffed_not_judged(tmp_path):
    # the invariant (qbank_memory.py:83-90) stays: a required box is never declined; it is
    # not even a judge() question — the human decides it at the escalation boundary.
    conn = _db(tmp_path)
    judge, seen = _recording_judge()
    label = "I consent to receive update messages by email"
    decisions, needs = answer_fields([_f("#m", label, required=True)], _ctx(conn, judge=judge))
    assert [d.ref for d in decisions] == []                  # NO decision at all
    assert seen == []                                        # judge() never saw it
    assert [f.ref for f in needs] == ["#m"]                  # it IS at the human boundary
    row = _row(conn, "run", "#m")
    assert row["source"] == dc.SOURCE and row["status"] == "needs_answer"
    assert "held back" in row["basis"] and "required" in row["basis"]


def test_optional_widget_without_a_no_option_is_undecided_and_recorded(tmp_path):
    conn = _db(tmp_path)
    # optional free-text combobox (or ["Opt in","Opt out"]): nothing to stuff, nothing to ask
    decisions, needs = answer_fields(
        [_f("#cb", "Get email updates", "combobox"),
         _f("#r", "Get email updates", "radio_group", False, ["Opt in", "Opt out"])], _ctx(conn))
    assert decisions == [] and needs == []
    for ref in ("#cb", "#r"):
        row = _row(conn, "run", ref)
        assert row["source"] == dc.SOURCE and row["status"] == "held"
        assert "no option expresses 'No'" in row["basis"]
    rows = conn.execute("SELECT COUNT(*) FROM application_qa WHERE status='held'").fetchone()[0]
    assert rows == 2


def test_status_consent_reaches_the_human_the_same_way_as_before(tmp_path):
    # the Gulf counter-example passes through the ladder untouched: map_screen -> judge -> human
    conn = _db(tmp_path)
    judge, seen = _recording_judge()
    decisions, needs = answer_fields(
        [_f("#g", "Please notify me of the status of my application via email", required=True)],
        _ctx(conn, judge=judge))
    assert decisions == [] and [f.ref for f in needs] == ["#g"] and seen == ["#g"]
    row = _row(conn, "run", "#g")
    assert row["source"] is None            # no decline-gate row: the ladder's business


def test_a_humans_prior_yes_survives_the_gate(tmp_path):
    """The human ticked the opt-in themselves on an earlier run: the gate must not override them."""
    conn = _db(tmp_path)
    qa_store.record(conn, job_id=7, run_key="old", ref="#m",
                    label="I want to be considered for other job opportunities",
                    answer="yes", source="human", status="answered")
    decisions, needs = answer_fields(
        [_f("#m", "I want to be considered for other job opportunities")], _ctx(conn))
    prior = [d for d in decisions if d.source == "human_prior"]
    assert [(d.value, d.action) for d in prior] == [(True, "check")] and needs == []
    assert not any(d.source == dc.SOURCE for d in decisions)


def test_non_marketing_ladder_unchanged(tmp_path):
    conn = _db(tmp_path)
    named = CandidateProfile(contact={"full_name": "Rakshit"})
    decisions, needs = answer_fields(
        [_f("#n", "Full name", purpose="full_name"),
         _f("#q", "Why do you want this job?", "textarea", required=True)],
        _ctx(conn, profile=named))
    assert {d.ref for d in decisions} == {"#n"} and [f.ref for f in needs] == ["#q"]
    assert not any(getattr(d, "basis", "") for d in decisions)


# ── autonomy: declined forms stay eligible (red-team C-2) ────────────────────

def test_autonomy_allow_a_form_with_a_policy_decline(tmp_path):
    conn = _db(tmp_path)
    autonomy.ensure(conn)
    qa_store.set_setting(conn, "autosubmit_career_site", "1")
    url = "https://careers.example.com/apply"
    autonomy.record_submission(conn, 7, "none", {}, "manual", url)     # a confirmed submit on this site once
    decisions = [
        {"ref": "#e", "label": "Email", "value": "a@b.co", "source": "resume"},
        {"ref": "#m", "label": "Get email updates for the latest senior data scientist jobs",
         "value": False, "source": dc.SOURCE},
    ]
    report = autonomy.autonomy_report(conn, "run", decisions)
    assert report["ok"] and report["blockers"] == []
    policy = autonomy.autosubmit_policy(conn, url, "run", decisions)
    assert policy["allow"], policy["reasons"]


def test_a_kept_decline_is_k_not_an_edit(tmp_path):
    # read-back of an unticked box comes back empty: that IS the decline, auditable as "kept"
    conn = _db(tmp_path)
    autonomy.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="run", ref="#m",
                    label="Get email updates for the latest senior data scientist jobs",
                    answer="False", source=dc.SOURCE, status="filled")
    out = autonomy.record_submission(conn, 7, "run",
                                     {"get email updates for the latest senior data scientist jobs": ""}, "manual")
    assert out == {"approved": 1, "edited": 0}
    row = conn.execute("SELECT outcome FROM application_qa WHERE run_key='run' AND ref='#m'").fetchone()
    assert row[0] == "kept"
