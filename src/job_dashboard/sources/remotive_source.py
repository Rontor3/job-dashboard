import requests

from job_dashboard.models import JobListing

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"


def fetch_remotive_jobs(search_term, limit=50):
    response = requests.get(
        REMOTIVE_API_URL, params={"search": search_term, "limit": limit}, timeout=15
    )
    response.raise_for_status()
    data = response.json()
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(
            JobListing(
                source="remotive",
                external_id=str(item.get("id")),
                title=item.get("title"),
                company=item.get("company_name"),
                location=item.get("candidate_required_location"),
                description=item.get("description") or "",
                job_url=item.get("url"),
                job_type=item.get("job_type"),
                is_remote=True,
                salary_text=item.get("salary") or None,
                posted_date=item.get("publication_date"),
            )
        )
    return jobs
