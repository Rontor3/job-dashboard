"""A board run that reached the employer's site saves that page as the job's apply link, so the next run (the queue's
job_target) starts there instead of on the board and its bot check (Opella, live 2026-10-24)."""
import sqlite3

from career_agent.apply import remember_employer_link
from job_dashboard.apply.queue_runner import job_target

WD = "https://opella.wd103.myworkdayjobs.com/en-US/OpellaCareers/job/Hyderabad/AI-Solution-expert_R70002658"


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, job_url TEXT, apply_kind TEXT, apply_url TEXT)")
    c.execute("INSERT INTO jobs VALUES (1, 'https://in.indeed.com/viewjob?jk=140decd767f49625', NULL, NULL)")
    c.execute("INSERT INTO jobs VALUES (2, 'https://in.indeed.com/viewjob?jk=2', 'external', 'https://acme.test/apply')")
    return c


def test_the_employer_page_becomes_the_next_start():
    c = _db()
    remember_employer_link(c, 1, WD)
    row = dict(zip(("id", "job_url", "apply_kind", "apply_url"), c.execute("SELECT * FROM jobs WHERE id=1").fetchone()))
    assert job_target(row) == WD


def test_an_existing_external_link_is_kept():
    c = _db()
    remember_employer_link(c, 2, WD)
    assert c.execute("SELECT apply_url FROM jobs WHERE id=2").fetchone()[0] == "https://acme.test/apply"
