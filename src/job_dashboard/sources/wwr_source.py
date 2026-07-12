import feedparser

from job_dashboard.models import JobListing


def fetch_wwr_jobs(feed_url="https://weworkremotely.com/categories/remote-programming-jobs.rss"):
    parsed = feedparser.parse(feed_url)
    jobs = []
    for entry in parsed.entries:
        raw_title = entry.get("title", "")
        jobs.append(
            JobListing(
                source="weworkremotely",
                title=_job_title(raw_title),
                company=_company(raw_title),
                location="Remote",
                description=entry.get("summary", ""),
                job_url=entry.get("link"),
                job_type=None,
                is_remote=True,
                posted_date=entry.get("published"),
            )
        )
    return jobs


def _job_title(raw_title):
    # WWR titles are formatted "Company: Job Title"
    return raw_title.split(":", 1)[1].strip() if ":" in raw_title else raw_title


def _company(raw_title):
    return raw_title.split(":", 1)[0].strip() if ":" in raw_title else "Unknown"
