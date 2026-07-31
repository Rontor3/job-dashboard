"""Assemble a per-job application package: profile + most-recent resume +
OPTIONAL most-recent cover letter + job detail. Never requires a letter.
"""
from job_dashboard.db import (
    cover_letters_for_job, job_detail, resumes_for_job,
)
from job_dashboard.apply.store import get_application_profile


def assemble_application_package(conn, job_id):
    resumes = resumes_for_job(conn, job_id) or []
    letters = cover_letters_for_job(conn, job_id) or []
    return {
        "profile": get_application_profile(conn),
        "resume": resumes[0] if resumes else None,
        "cover_letter": letters[0] if letters else None,  # OPTIONAL
        "job": job_detail(conn, job_id),
    }
