from career_agent.browser.form_model import guess_purpose
from career_agent.browser.page_prep import _looks_closed


def test_role_mention_not_tagged_job_title():
    # "for this role" is a reference to the position, not a job-title input
    assert guess_purpose("Are you open to relocation for this role?", "select") == "willing_to_relocate"
    assert guess_purpose("Have you interviewed for this role in the last 3 months?", "select") != "job_title"
    # genuine job-title fields still resolve
    assert guess_purpose("Job Title", "text") == "job_title"
    assert guess_purpose("Position Title", "text") == "job_title"
    assert guess_purpose("Current Position", "text") == "job_title"


def test_looks_closed_detects_dead_postings():
    assert _looks_closed("Job not found\n\nThe job you requested was not found.\n\nView all open positions")
    assert _looks_closed("Sorry, we couldn't find anything here. The job posting ... has closed ... (404 error).")
    assert _looks_closed("This job is no longer available. VIEW ALL JOBS")
    # a real form / JD must NOT be flagged
    assert not _looks_closed("Apply for this job. First Name, Last Name, Email, Resume. Why do you want to work here?")
    assert not _looks_closed("")     # empty -> unknown, not 'closed'
