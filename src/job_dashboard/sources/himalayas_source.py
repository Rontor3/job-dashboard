import requests

from job_dashboard.models import JobListing

HIMALAYAS_SEARCH_URL = "https://himalayas.app/jobs/api/search"


def fetch_himalayas_jobs(query, employment_type=None):
    params = {"q": query}
    if employment_type:
        params["employment_type"] = employment_type
    response = requests.get(HIMALAYAS_SEARCH_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(
            JobListing(
                source="himalayas",
                external_id=item.get("guid"),
                title=item.get("title"),
                company=item.get("companyName"),
                location=", ".join(item.get("locationRestrictions") or []) or "Worldwide",
                description=item.get("description") or "",
                job_url=item.get("applicationLink"),
                job_type=item.get("employmentType"),
                is_remote=True,
                salary_text=_format_salary(item),
                posted_date=item.get("pubDate"),
            )
        )
    return jobs


def _format_salary(item):
    lo, hi, cur = item.get("minSalary"), item.get("maxSalary"), item.get("currency")
    if lo is None and hi is None:
        return None
    return f"{lo or ''}-{hi or ''} {cur or ''}".strip()
