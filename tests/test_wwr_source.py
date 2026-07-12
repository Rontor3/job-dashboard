import feedparser

from job_dashboard.sources import wwr_source

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>We Work Remotely</title>
<item>
<title>Acme Corp: Senior Machine Learning Engineer</title>
<link>https://weworkremotely.com/remote-jobs/acme-corp-senior-machine-learning-engineer</link>
<description>&lt;p&gt;Full job description text&lt;/p&gt;</description>
<pubDate>Sat, 05 Jul 2026 00:00:00 +0000</pubDate>
</item>
</channel>
</rss>"""


def test_fetch_wwr_jobs_splits_company_from_title(monkeypatch):
    real_parse = feedparser.parse  # capture before patching (same module object)
    monkeypatch.setattr(
        wwr_source.feedparser, "parse", lambda url: real_parse(SAMPLE_RSS)
    )

    jobs = wwr_source.fetch_wwr_jobs()

    assert len(jobs) == 1
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].title == "Senior Machine Learning Engineer"
    assert jobs[0].job_url.startswith("https://weworkremotely.com")
    assert jobs[0].is_remote is True


RSS_WITH_EMPTY_DESCRIPTION = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>We Work Remotely</title>
<item>
<title>Empty Co: No Description Role</title>
<link>https://weworkremotely.com/remote-jobs/empty-co-no-description-role</link>
<description></description>
<pubDate>Sat, 05 Jul 2026 00:00:00 +0000</pubDate>
</item>
<item>
<title>Real Co: Machine Learning Engineer</title>
<link>https://weworkremotely.com/remote-jobs/real-co-machine-learning-engineer</link>
<description>&lt;p&gt;Actual job description text&lt;/p&gt;</description>
<pubDate>Sat, 05 Jul 2026 00:00:00 +0000</pubDate>
</item>
</channel>
</rss>"""


def test_fetch_wwr_jobs_skips_items_without_description(monkeypatch):
    real_parse = feedparser.parse  # capture before patching (same module object)
    monkeypatch.setattr(
        wwr_source.feedparser, "parse",
        lambda url: real_parse(RSS_WITH_EMPTY_DESCRIPTION),
    )

    jobs = wwr_source.fetch_wwr_jobs()

    assert len(jobs) == 1
    assert jobs[0].company == "Real Co"
