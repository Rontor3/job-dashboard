import requests

from job_dashboard.models import JobListing

REMOTEOK_API_URL = "https://remoteok.com/api"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobDashboardBot/1.0)"}


def fetch_remoteok_jobs():
    response = requests.get(REMOTEOK_API_URL, headers=_HEADERS, timeout=15)
    response.raise_for_status()
    data = response.json()
    jobs = []
    for item in data:
        if "position" not in item:
            continue  # first element is the API's legal notice, not a job
        description = item.get("description")
        if description is None or not str(description).strip():
            # Project constraint: every JobListing carries full description
            # text; rows lacking one are skipped.
            continue
        jobs.append(
            JobListing(
                source="remoteok",
                external_id=str(item.get("id")),
                title=item.get("position"),
                company=item.get("company"),
                location=item.get("location") or "Remote",
                description=description,
                job_url=item.get("apply_url") or item.get("url"),
                job_type="contract" if "contract" in (item.get("tags") or []) else None,
                is_remote=True,
                salary_text=_format_salary(item),
                posted_date=item.get("date"),
            )
        )
    return jobs


def _format_salary(item):
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if not lo and not hi:
        return None
    return f"${lo or ''}-${hi or ''}"
