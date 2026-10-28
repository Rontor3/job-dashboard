"""A career site saying you already applied ends the run as already_applied (-> the tracker's 'applied'), not as
no_advance_control / failed (Wipro SuccessFactors, live 2026-10-23)."""
from types import SimpleNamespace as NS

from career_agent.browser.page_prep import says_already_applied
from job_dashboard.apply.outcome import outcome


def _page(text):
    return NS(evaluate=lambda js: text)


def test_the_sites_own_words_are_read():
    assert says_already_applied(_page("DATA SCIENTIST L3\nYou already applied for this position.\nBack to Job Listings"))
    assert says_already_applied(_page("You've already applied"))
    assert says_already_applied(_page("Applied 3 days ago"))
    assert not says_already_applied(_page("Apply now. Posted 3 days ago. Have you applied before? Tell us."))
    assert not says_already_applied(_page("x" * 3500 + " You already applied"))       # the top of the page only


def test_already_applied_is_done_and_applied_in_the_tracker():
    assert outcome({"stopped_reason": "already_applied"}, 0) == ("done", "already_applied", "applied")
