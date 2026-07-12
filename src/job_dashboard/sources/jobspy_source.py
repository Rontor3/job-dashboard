import math

from jobspy import scrape_jobs

from job_dashboard.models import JobListing


def _clean(v):
    """Return v unless it's None or a float NaN (pandas' stand-in for missing).

    pandas upcasts numeric columns to float64 when any row is missing a
    value, turning that missing value into NaN instead of None. bool(nan)
    is True and str(nan) == "nan", so every row.get(...) must be routed
    through this before any truthiness check or str() conversion.
    """
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _format_amount(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


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
        description = _clean(row.get("description"))
        if description is None or not str(description).strip():
            # Project constraint: every JobListing carries full description
            # text; rows lacking one are skipped.
            continue

        job_id = _clean(row.get("id"))
        is_remote = _clean(row.get("is_remote"))
        date_posted = _clean(row.get("date_posted"))

        jobs.append(
            JobListing(
                source=f"jobspy:{_clean(row.get('site'))}",
                external_id=str(job_id) if job_id is not None else None,
                title=_clean(row.get("title")),
                company=_clean(row.get("company")),
                location=_clean(row.get("location")),
                description=description,
                job_url=_clean(row.get("job_url")),
                job_type=_clean(row.get("job_type")),
                is_remote=bool(is_remote) if is_remote is not None else None,
                salary_text=_format_salary(row),
                posted_date=str(date_posted) if date_posted is not None else None,
            )
        )
    return jobs


def _format_salary(row):
    lo = _clean(row.get("min_amount"))
    hi = _clean(row.get("max_amount"))
    cur = _clean(row.get("currency"))
    if lo is None and hi is None:
        return None
    return f"{_format_amount(lo)}-{_format_amount(hi)} {cur or ''}".strip()
