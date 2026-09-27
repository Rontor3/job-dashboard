from datetime import datetime, timezone

from job_dashboard.dateparse import normalize_posted_date

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def test_epoch_seconds_and_millis():
    assert normalize_posted_date("1789082478") == "2026-09-10T23:21:18+00:00"
    assert normalize_posted_date("1789082478000") == "2026-09-10T23:21:18+00:00"


def test_relative_text():
    assert normalize_posted_date("Today", now=NOW) == NOW.isoformat()
    assert normalize_posted_date("Yesterday", now=NOW) == "2026-09-26T12:00:00+00:00"
    assert normalize_posted_date("3 Days Ago", now=NOW) == "2026-09-24T12:00:00+00:00"
    assert normalize_posted_date("2 hours ago", now=NOW) == "2026-09-27T10:00:00+00:00"


def test_already_iso_passes_through_normalized():
    assert normalize_posted_date("2026-09-27") == "2026-09-27T00:00:00"
    assert normalize_posted_date("2026-09-16T10:10:53") == "2026-09-16T10:10:53"
    assert normalize_posted_date("2026-09-06T03:47:24+00:00") == "2026-09-06T03:47:24+00:00"


def test_empty_and_unparseable():
    assert normalize_posted_date(None) is None
    assert normalize_posted_date("") is None
    assert normalize_posted_date("sometime soon") == "sometime soon"
