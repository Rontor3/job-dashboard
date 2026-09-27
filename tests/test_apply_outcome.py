import pytest

from job_dashboard.apply.outcome import outcome


@pytest.mark.parametrize("result, code, want", [
    ({"submitted": True, "stopped_reason": "submitted"}, 0, ("done", "submitted", "applied")),
    ({"submitted": False, "stopped_reason": "ready_for_review"}, 0, ("parked", "review", None)),
    ({"submitted": False, "stopped_reason": "apply_is_one_click"}, 0, ("parked", "one_click_needs_autosubmit", None)),
    ({"submitted": False, "stopped_reason": "logged_out"}, 0, ("parked", "logged_out", None)),
    ({"submitted": False, "stopped_reason": "challenge"}, 0, ("parked", "challenge", None)),
    ({"submitted": False, "stopped_reason": "daily_cap"}, 0, ("parked", "daily_cap", None)),
    ({"submitted": False, "stopped_reason": "captcha_blocked"}, 0, ("parked", "captcha_blocked", None)),
    ({"submitted": False, "stopped_reason": "gap", "pending_human": ["CTC"]}, 0, ("parked", "needs_answers", None)),
    ({"submitted": False, "stopped_reason": "not_approved"}, 0, ("parked", "not_approved", None)),
    ({"submitted": False, "stopped_reason": "dry_run"}, 0, ("parked", "needs_approval", None)),
    (None, 1, ("failed", "crashed", "failed")),
    (None, 0, ("failed", "no_result", "failed")),
    ({"submitted": False, "stopped_reason": "error"}, 1, ("failed", "error", "failed")),
])
def test_outcome_table(result, code, want):
    assert outcome(result, code) == want


def test_submitted_wins_over_a_nonzero_exit():
    # The board confirmed the application; a crash while tidying up must not
    # turn a real submission into "failed".
    assert outcome({"submitted": True}, 1) == ("done", "submitted", "applied")
