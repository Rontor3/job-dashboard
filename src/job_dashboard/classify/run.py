"""Batch: classify every not-yet-classified company. Idempotent."""
from job_dashboard.db import (
    unclassified_companies, upsert_company_classification, get_sample_job_for_company,
)
from job_dashboard.classify.company import classify_company


def classify_unclassified(conn, llm=None, limit=None):
    keys = unclassified_companies(conn)
    if limit is not None:
        keys = keys[:limit]
    counts = {"dict": 0, "llm": 0, "other": 0, "total": 0}
    for key in keys:
        title, desc, display = get_sample_job_for_company(conn, key)
        industry, ctype, method = classify_company(display or key, title, desc, llm=llm)
        upsert_company_classification(conn, key, industry, ctype, method)
        counts[method] = counts.get(method, 0) + 1
        counts["total"] += 1
    return counts
