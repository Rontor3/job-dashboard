import json

import pytest

from job_dashboard import rank_io
from job_dashboard.db import init_db, insert_job, upsert_embed_score
from job_dashboard.models import JobListing


def _seed(tmp_path):
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    insert_job(conn, JobListing(source="s", title="ML Engineer", company="Acme",
                                job_url="https://x.com/1", description="jd"))
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    upsert_embed_score(conn, job_id, 0.9, "h")
    conn.close()
    return db_path, job_id


def test_top_prints_json_of_unranked_jobs(tmp_path, capsys):
    db_path, job_id = _seed(tmp_path)

    exit_code = rank_io.main(["top", "--db", str(db_path), "--limit", "5"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == job_id
    assert payload[0]["embed_score"] == 0.9


def test_record_writes_evaluation(tmp_path):
    db_path, job_id = _seed(tmp_path)
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps({
        "llm_score": 82, "verdict": "Strong Fit",
        "strengths": ["production ML"], "gaps": ["k8s"], "flags": {},
    }))

    exit_code = rank_io.main([
        "record", "--db", str(db_path), "--job-id", str(job_id),
        "--file", str(eval_file),
    ])

    assert exit_code == 0
    conn = init_db(db_path)
    row = conn.execute(
        "SELECT llm_score, verdict FROM match_scores WHERE job_id = ?", (job_id,)
    ).fetchone()
    assert row == (82, "Strong Fit")


def test_record_rejects_invalid_payload_with_exit_1(tmp_path, capsys):
    db_path, job_id = _seed(tmp_path)
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps({
        "llm_score": 999, "verdict": "Strong Fit",
        "strengths": [], "gaps": [], "flags": {},
    }))

    exit_code = rank_io.main([
        "record", "--db", str(db_path), "--job-id", str(job_id),
        "--file", str(eval_file),
    ])

    assert exit_code == 1
    assert "llm_score" in capsys.readouterr().err
