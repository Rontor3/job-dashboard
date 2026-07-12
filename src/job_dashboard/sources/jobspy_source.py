from jobspy import scrape_jobs

from job_dashboard.models import JobListing


def fetch_jobspy_jobs(search_term, location, site_names, results_wanted=20):
    df = scrape_jobs(
        site_name=site_names,
        search_term=search_term,
        location=location,
        results_wanted=results_wanted,
        description_format="markdown",
    )
    jobs = []
    for _, row in df.iterrows():
        jobs.append(
            JobListing(
                source=f"jobspy:{row.get('site')}",
                external_id=str(row.get("id")) if row.get("id") is not None else None,
                title=row.get("title"),
                company=row.get("company"),
                location=row.get("location"),
                description=row.get("description") or "",
                job_url=row.get("job_url"),
                job_type=row.get("job_type"),
                is_remote=bool(row.get("is_remote")) if row.get("is_remote") is not None else None,
                salary_text=_format_salary(row),
                posted_date=str(row.get("date_posted")) if row.get("date_posted") is not None else None,
            )
        )
    return jobs


def _format_salary(row):
    lo, hi, cur = row.get("min_amount"), row.get("max_amount"), row.get("currency")
    if not lo and not hi:
        return None
    return f"{lo or ''}-{hi or ''} {cur or ''}".strip()
