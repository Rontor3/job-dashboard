import pytest

from job_dashboard.db import (
    canonical_jobs_for_dedup, init_db, insert_job, jobs_needing_embed_score,
    mark_duplicate, record_llm_evaluation, suspected_duplicates,
    top_unranked_jobs, upsert_embed_score,
)
from job_dashboard.models import JobListing


def _job(n, **overrides):
    fields = dict(
        source=f"src{n}", title=f"Role {n}", company=f"Co {n}",
        job_url=f"https://example.com/{n}", description=f"desc {n}",
    )
    fields.update(overrides)
    return JobListing(**fields)


def test_upsert_embed_score_then_needing_list_shrinks(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]

    assert jobs_needing_embed_score(conn, "hashA") == [(job_id, "desc 1")]
    upsert_embed_score(conn, job_id, 0.82, "hashA")
    assert jobs_needing_embed_score(conn, "hashA") == []


def test_stale_profile_hash_marks_job_as_needing_rescore(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    upsert_embed_score(conn, job_id, 0.82, "hashA")

    assert jobs_needing_embed_score(conn, "hashB") == [(job_id, "desc 1")]


def test_reupsert_resets_llm_fields(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    upsert_embed_score(conn, job_id, 0.82, "hashA")
    record_llm_evaluation(conn, job_id, 74, "Good Fit", ["s"], ["g"], {})

    upsert_embed_score(conn, job_id, 0.5, "hashB")

    row = conn.execute(
        "SELECT llm_score, verdict FROM match_scores WHERE job_id = ?", (job_id,)
    ).fetchone()
    assert row == (None, None)


def test_record_llm_evaluation_validates_inputs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]

    with pytest.raises(ValueError):  # no embed score yet
        record_llm_evaluation(conn, job_id, 74, "Good Fit", [], [], {})

    upsert_embed_score(conn, job_id, 0.8, "h")
    with pytest.raises(ValueError):
        record_llm_evaluation(conn, job_id, 101, "Good Fit", [], [], {})
    with pytest.raises(ValueError):
        record_llm_evaluation(conn, job_id, 74, "Amazing Fit", [], [], {})


def test_top_unranked_orders_by_embed_score_and_skips_duplicates_and_ranked(tmp_path):
    conn = init_db(tmp_path / "t.db")
    for n in (1, 2, 3, 4):
        insert_job(conn, _job(n))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]
    upsert_embed_score(conn, ids[0], 0.9, "h")
    upsert_embed_score(conn, ids[1], 0.7, "h")
    upsert_embed_score(conn, ids[2], 0.95, "h")
    upsert_embed_score(conn, ids[3], 0.99, "h")
    record_llm_evaluation(conn, ids[0], 80, "Strong Fit", [], [], {})  # already ranked
    mark_duplicate(conn, ids[3], ids[2])                               # duplicate

    top = top_unranked_jobs(conn, limit=10)

    assert [j["id"] for j in top] == [ids[2], ids[1]]
    assert top[0]["embed_score"] == 0.95


def test_mark_and_list_suspected_duplicates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1, source="jobspy:linkedin"))
    insert_job(conn, _job(2, source="remoteok"))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]

    mark_duplicate(conn, ids[1], ids[0])
    dupes = suspected_duplicates(conn)

    assert len(dupes) == 1
    assert dupes[0]["id"] == ids[1]
    assert dupes[0]["duplicate_of"] == ids[0]
    assert dupes[0]["canonical_source"] == "jobspy:linkedin"


def test_canonical_jobs_for_dedup_excludes_marked_rows(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1))
    insert_job(conn, _job(2))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]
    mark_duplicate(conn, ids[1], ids[0])

    rows = canonical_jobs_for_dedup(conn)
    assert [r[0] for r in rows] == [ids[0]]


def test_init_db_upgrades_existing_database_in_place(tmp_path):
    # simulate a pre-matching database: create it, then re-open via init_db
    path = tmp_path / "t.db"
    conn = init_db(path)
    insert_job(conn, _job(1))
    conn.close()

    conn2 = init_db(path)  # must not fail on existing duplicate_of / match_scores
    cols = [r[1] for r in conn2.execute("PRAGMA table_info(jobs)").fetchall()]
    assert "duplicate_of" in cols
