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


class _FakePage:
    """Dispatches page.evaluate by the JS it's handed: the big classify probe
    returns `d`; the body-innerText read returns `body`."""
    def __init__(self, d, body=""): self._d = d; self._body = body
    def evaluate(self, js):
        return self._body if "document.body.innerText" in js and "hasPw" not in js else self._d


def _d(fillable=0, hasPw=False, hasEmail=False, verify=False):
    return {"fillable": fillable, "hasPw": hasPw, "hasEmail": hasEmail, "verify": verify}


def test_classify_404_status_is_decisive():
    from career_agent.browser.page_prep import classify_entry
    assert classify_entry(_FakePage(_d(fillable=5)), status=404) == "closed"   # even with a form


def test_classify_form_present_never_closed():
    from career_agent.browser.page_prep import classify_entry
    # a real form that happens to contain '404' text is a form, not closed
    p = _FakePage(_d(fillable=6), body="...error 404 error somewhere in a long JD..." * 40)
    assert classify_entry(p, status=200) == "form"


def test_classify_no_form_plus_dead_language_is_closed():
    from career_agent.browser.page_prep import classify_entry
    p = _FakePage(_d(fillable=0), body="Job not found\nThe job you requested was not found.")
    assert classify_entry(p) == "closed"


def test_classify_no_form_but_alive_is_none_not_closed():
    from career_agent.browser.page_prep import classify_entry
    p = _FakePage(_d(fillable=0), body="Loading your application… please wait")
    assert classify_entry(p) == "none"        # alive but unreached -> not 'closed'


def test_apply_url_variants():
    from career_agent.browser.page_prep import _apply_url_variants
    assert _apply_url_variants("https://jobs.lever.co/co/abc-123") == ["https://jobs.lever.co/co/abc-123/apply"]
    assert _apply_url_variants("https://jobs.ashbyhq.com/co/abc?src=x") == ["https://jobs.ashbyhq.com/co/abc/application"]
    assert _apply_url_variants("https://jobs.lever.co/co/abc/apply") == []          # already there
    assert _apply_url_variants("https://acme.com/careers/42") == ["https://acme.com/careers/42/apply"]  # generic
