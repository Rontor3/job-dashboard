import re

from job_dashboard.db import canonical_jobs_for_dedup, mark_duplicate


def normalized_key(company, title):
    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

    return f"{norm(company)}|{norm(title)}"


def mark_duplicates(conn):
    """Group canonical jobs by normalized (company, title); earliest-fetched row
    (tie-broken by id) stays canonical, the rest are marked duplicate_of it.
    Marked rows are never deleted — deletion is an explicit user command later."""
    groups = {}
    for job_id, company, title, fetched_at, _source in canonical_jobs_for_dedup(conn):
        groups.setdefault(normalized_key(company, title), []).append((fetched_at, job_id))

    marked = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort()
        canonical_id = rows[0][1]
        for _, dup_id in rows[1:]:
            mark_duplicate(conn, dup_id, canonical_id)
            marked += 1
    return marked
