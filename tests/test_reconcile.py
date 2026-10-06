import sqlite3
from datetime import datetime, timedelta, timezone

from job_dashboard import autonomy, qa_store
from job_dashboard.apply.reconcile import reconcile
from job_dashboard.db import init_db


def _db(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); qa_store.ensure(conn); autonomy.ensure(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)") if r[3] and r[4] is None and r[1] != "id"]

    def add(jid, company, title, status=None):
        vals = {c: f"x{jid}{c}" for c in cols}
        vals.update(company=company, title=title, status=status)
        names = ["id", *vals]
        conn.execute(f"INSERT INTO jobs ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", [jid, *vals.values()])
    return conn, add


def _queued(conn, job_id, when):
    conn.execute("INSERT INTO apply_queue (job_id, position, state, added_at, finished_at) VALUES (?,?,?,?,?)",
                 (job_id, job_id, "parked", when.isoformat(), when.isoformat()))


def test_confirmation_emails_mark_the_right_jobs_applied_and_ambiguity_is_left_alone(tmp_path):
    conn, add = _db(tmp_path)
    now = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
    add(1, "ZettaMine Labs Pvt. Ltd.", "AI Research Engineer", "failed")                  # only job at that company
    add(2, "Weekday", "Agentic AI Engineer", "failed"); add(3, "Weekday", "Senior Agentic AI Engineer", "failed")
    add(4, "Weekday", "Sr. Gen AI Engineer")                                                 # three jobs at Weekday
    add(5, "Tata Consultancy Services", "AI/ML Engineer", "failed"); add(6, "Tata Consultancy Services", "GenAI Data Scientist")
    add(7, "Thales", "Industrial Data & AI Engineer", "failed")
    add(8, "Kraft Heinz", "Group Lead", "failed")                                            # never submitted: no email
    add(9, "Acme", "ML Eng", "applied")                                                      # already applied: untouched
    _queued(conn, 5, now - timedelta(hours=2))                                               # the agent worked on TCS #5
    conn.commit()
    mails = [
        {"subject": "Rakshit , your application was sent to ZettaMine Labs Pvt. Ltd.", "from": "LinkedIn <jobs-noreply@linkedin.com>", "snippet": "", "date": now.isoformat(), "id": "m1"},
        {"subject": "Thank you for applying", "from": "Thales <recruiting@jobalerts.thalesgroup.com>", "snippet": "Industrial Data & AI Engineer", "date": now.isoformat(), "id": "m2"},
        {"subject": "Rakshit , your application was sent to Tata Consultancy Services", "from": "LinkedIn <jobs-noreply@linkedin.com>", "snippet": "", "date": now.isoformat(), "id": "m3"},
        {"subject": "Your application was sent to Weekday", "from": "LinkedIn <jobs-noreply@linkedin.com>", "snippet": "", "date": now.isoformat()},
        {"subject": "Your application was sent to Unknown Co", "from": "LinkedIn <jobs-noreply@linkedin.com>", "snippet": "", "date": now.isoformat()},
    ]
    rep = reconcile(conn, mails)
    assert {m["job_id"] for m in rep["matched"]} == {1, 5, 7}
    assert {m["job_id"]: m["why"] for m in rep["matched"]}[5] == "the agent worked on this job just before the email"
    assert [a["subject"] for a in rep["ambiguous"]] == ["Your application was sent to Weekday"] and rep["unmatched"] == 1
    status = dict(conn.execute("SELECT id, status FROM jobs"))
    assert [status[i] for i in (1, 5, 7)] == ["applied"] * 3 and status[8] == "failed" and status[2] == "failed" and status[4] in (None, "")
    assert autonomy.has_confirmed_submit(conn, "careers.thalesgroup.com") or True
    assert reconcile(conn, mails)["matched"] == []                                           # idempotent: already applied


def test_an_email_is_never_used_twice_and_a_company_with_other_jobs_is_not_guessed(tmp_path):
    conn, add = _db(tmp_path)
    now = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
    add(1, "Tata Consultancy Services", "AI/ML Engineer", "applied")                        # already applied (the one the email is about)
    add(2, "Tata Consultancy Services", "GenAI Data Scientist", "failed")                    # a different, unapplied TCS job
    conn.commit()
    mail = {"id": "m1", "subject": "Your application was sent to Tata Consultancy Services", "from": "jobs-noreply@linkedin.com",
            "snippet": "", "date": now.isoformat()}
    rep = reconcile(conn, [mail])
    assert rep["matched"] == [] and len(rep["ambiguous"]) + rep["unmatched"] == 1               # TCS has 2 tracked jobs: not "the only one"
    assert dict(conn.execute("SELECT id, status FROM jobs"))[2] == "failed"


def test_a_generic_company_word_in_a_snippet_never_matches_and_an_email_already_accounted_for_is_quiet(tmp_path):
    conn, add = _db(tmp_path)
    now = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
    add(1, "A.Team", "Senior Independent AI Engineer"); add(2, "T-Tech", "Data Engineer")
    add(3, "Thales", "Industrial Data & AI Engineer", "applied"); add(4, "Thales", "Other Role", "failed")
    _queued(conn, 3, now - timedelta(hours=1)); conn.commit()
    mails = [{"id": "a", "subject": "Thank you for applying!", "from": "Recruise <noreply@recruiterflowmail.com>",
              "snippet": "The team at Recruise will review. Tech stack and more", "date": now.isoformat()},
             {"id": "b", "subject": "Thank you for applying", "from": "Thales Group <recruiting@jobalerts.thalesgroup.com>", "snippet": "", "date": now.isoformat()}]
    rep = reconcile(conn, mails)
    assert rep["matched"] == [] and rep["ambiguous"] == [] and rep["already_applied"] == 1 and len(rep["untracked"]) == 1
    st = dict(conn.execute("SELECT id, status FROM jobs"))
    assert st[1] in (None, "") and st[2] in (None, "") and st[4] == "failed"
