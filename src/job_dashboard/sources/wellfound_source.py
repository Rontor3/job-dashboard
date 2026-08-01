"""Normalizer for browser-ingested Wellfound job feeds (no I/O).

Wellfound requires a logged-in session, so jobs are extracted by a browser
agent (see docs/wellfound-ingest-runbook.md) and handed here as raw dicts.
This module turns those raw dicts into JobListing rows; it never fetches
anything itself.
"""

from job_dashboard.models import JobListing


def wellfound_jobs_from_raw(raw):
    jobs = []
    for item in raw:
        try:
            if not isinstance(item, dict):
                continue

            slug = item.get("slug")
            title = item.get("title")
            company = item.get("company")
            if not slug or not title or not company:
                continue

            description = _compose_description(item)
            if not description or not description.strip():
                # Project constraint: every JobListing carries full description
                # text; rows lacking one are skipped.
                continue

            jobs.append(
                JobListing(
                    source="wellfound",
                    job_url=f"https://wellfound.com/jobs/{slug}",
                    title=title,
                    company=company,
                    description=description,
                    location=item.get("location"),
                    is_remote=item.get("remote"),
                    salary_text=item.get("salary"),
                    external_id=slug,
                )
            )
        except Exception:
            continue
    return jobs


def _compose_description(item):
    base = item.get("description") or ""
    tail = ""

    years_experience = item.get("years_experience")
    if years_experience not in (None, ""):
        tail += f"\n\n{years_experience} years of exp"

    hires_remotely_in = item.get("hires_remotely_in")
    if hires_remotely_in:
        tail += f"\nHires remotely in: {hires_remotely_in}"

    return f"{base}{tail}"
