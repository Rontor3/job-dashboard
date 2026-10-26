"""A board's job-alert newsletter is not about your application (Glassdoor 'Data Scientist role at Weekday: you
would be a great fit!' with 'interview tips' moved Weekday to Interviewing, 2026-10-22)."""
from job_dashboard.mail_classify import keyword_classify
from job_dashboard.mail_scan import _JOB_ALERT, _is_board


def test_interview_tips_is_not_an_interview():
    r = keyword_classify("Data Scientist role at Weekday: you would be a great fit!",
                         "Check out the latest industry content about career advice, salary negotiations and interview tips")
    assert r["category"] != "interview"


def test_a_real_invitation_still_is():
    assert keyword_classify("Interview invitation - Data Scientist", "We would like to invite you to interview on Monday")["category"] == "interview"


def test_board_job_alerts_are_recognised():
    assert _is_board("noreply@glassdoor.com") and _is_board("jobmessenger@monsterindia.com")
    assert _JOB_ALERT.search("Data Scientist role at Weekday: you would be a great fit!")
    assert not _JOB_ALERT.search("Indeed Application: Associate Data Scientist")


def test_a_receipt_with_a_conditional_disclaimer_is_not_a_rejection():
    body = ("Thank you for applying for the Data Scientist position. We've received your application. "
            "If you don't hear from us, we've moved forward with other candidates.")
    assert keyword_classify("Thank you for your application at Coface", body)["category"] == "acknowledgement"
