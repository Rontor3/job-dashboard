"""Gaps seen on a live Indeed form (Coface): duration options, 'Other' follow-up box, consent tick."""
from types import SimpleNamespace as NS

from career_agent.browser.form_model import guess_purpose
from career_agent.memory.qbank_compose import option_for_days
from career_agent.orchestrator.answering import _drop_other_followups

OPTS = ["Immediately", "Within 2 weeks", "Within 1 month", "Within 2 months", "Other (please specify in the box below)"]


def test_notice_days_pick_the_covering_duration_option():
    assert option_for_days(OPTS, 30) == "Within 1 month"
    assert option_for_days(OPTS, 0) == "Immediately"
    assert option_for_days(["Yes", "No"], 30) is None


def test_other_followup_box_blank_unless_other_chosen():
    box = NS(ref="t", kind="text", label='In case you have selected "Other" for the question above, please specify your start date:')
    pick = lambda v: [NS(ref="r", value=v), NS(ref="t", value="July 2023")]
    assert _drop_other_followups([box], pick("Within 1 month"), [])[0][0].ref == "r" and len(_drop_other_followups([box], pick("Within 1 month"), [])[0]) == 1
    assert len(_drop_other_followups([box], pick("Other (please specify)"), [])[0]) == 2


def test_consent_statement_checkbox_is_an_attestation_but_a_question_is_not():
    assert guess_purpose("By applying for this job, you acknowledge that your application will be processed", "checkbox") == "attestation"
    assert guess_purpose("Do you agree to relocate?", "radio_group") != "attestation"


def test_total_experience_with_qualifiers_still_matches_by_shape():
    from career_agent.memory.qbank_match import _TOTAL_EXP
    assert _TOTAL_EXP.search("What is your total full-time work experience in Data Scientist / AI / ML (internships not included)?")
    assert not _TOTAL_EXP.search("Years of experience with Python")
