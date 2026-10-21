import sqlite3
from datetime import datetime, timedelta, timezone

from job_dashboard import autonomy, qa_store
from job_dashboard.apply.submit_watch import SubmitWatcher
from job_dashboard.db import init_db


class FakeTab:
    def __init__(self, url, values, confirmed=(False, "no confirmation text")):
        self.url, self._v, self._c = url, values, confirmed
    def read_values(self): return self._v
    def confirmed(self): return self._c


class FakeTabs:
    def __init__(self, tab=None): self.tab = tab
    def find(self, tab_id, url): return self.tab


def _setup(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    qa_store.ensure(conn); autonomy.ensure(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS run_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, url TEXT, job_id INTEGER,
                    stopped_reason TEXT, filled INTEGER, escalated INTEGER, submitted INTEGER, result_json TEXT)""")
    conn.commit()
    conn.execute("INSERT INTO jobs (id, job_url, title, company) VALUES (7, 'https://x/j', 'ML Eng', 'Acme')") if False else None
    return conn


def _job(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)") if r[3] and r[4] is None and r[1] != "id"]
    conn.execute(f"INSERT INTO jobs (id, {', '.join(cols)}) VALUES (7, {', '.join(repr('x'+str(i)) for i,_ in enumerate(cols))})")
    conn.commit()


def test_a_hand_submit_is_noticed_marked_applied_and_turned_into_approvals(tmp_path):
    conn = _setup(tmp_path); _job(conn)
    c = conn
    c.execute("CREATE TABLE IF NOT EXISTS qbank_entry (id TEXT PRIMARY KEY, answer TEXT)")
    c.execute("INSERT OR IGNORE INTO qbank_entry (id) VALUES ('notice_period')"); autonomy.ensure(c)
    qa_store.record(c, job_id=7, run_key="run1", ref="#a", label="Notice period", answer="30 days", source="qbank",
                    status="filled", retrieved_qkey="notice_period")
    w = SubmitWatcher(str(tmp_path / "t.db"))
    w.register(c, 7, "https://careers.example.com/apply?step=4", "run1", "TAB1")
    # 1) still on the form: values remembered, nothing finalized
    assert w.poll_once(c, FakeTabs(FakeTab("https://careers.example.com/apply?step=4", {"Notice period": "30 days"}))) == []
    assert c.execute("SELECT job_id FROM submission_watch").fetchone() == (7,)
    # 2) the page now confirms (the form is gone: nothing readable): the remembered values are the final ones
    done = w.poll_once(c, FakeTabs(FakeTab("https://careers.example.com/thanks", {}, (True, "page says 'application submitted'"))))
    assert done == [7]
    assert c.execute("SELECT status FROM jobs WHERE id=7").fetchone()[0] == "applied"
    assert c.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 0
    assert autonomy.approvals(c, "notice_period") == 1 and autonomy.has_confirmed_submit(c, "careers.example.com")
    assert c.execute("SELECT outcome FROM application_qa WHERE run_key='run1'").fetchone()[0] == "kept"


def test_an_answer_the_human_changed_before_submitting_resets_its_approvals(tmp_path):
    conn = _setup(tmp_path); _job(conn); c = conn
    c.execute("CREATE TABLE IF NOT EXISTS qbank_entry (id TEXT PRIMARY KEY, answer TEXT)")
    c.execute("INSERT OR IGNORE INTO qbank_entry (id) VALUES ('notice_period')"); autonomy.ensure(c)
    c.execute("UPDATE qbank_entry SET approvals=2 WHERE id='notice_period'"); c.commit()
    qa_store.record(c, job_id=7, run_key="run1", ref="#a", label="Notice period", answer="30 days", source="qbank",
                    status="filled", retrieved_qkey="notice_period")
    w = SubmitWatcher(str(tmp_path / "t.db")); w.register(c, 7, "https://x/apply", "run1", None)
    w.poll_once(c, FakeTabs(FakeTab("https://x/apply", {"Notice period": "60 days"})))          # the human edited it
    w.poll_once(c, FakeTabs(FakeTab("https://x/done", {}, (True, "ok"))))
    assert autonomy.approvals(c, "notice_period") == 0


def test_a_watch_whose_tab_is_gone_expires_after_two_days(tmp_path):
    conn = _setup(tmp_path); w = SubmitWatcher(str(tmp_path / "t.db"))
    w.register(conn, 7, "https://x/apply", "r", None)
    assert w.poll_once(conn, FakeTabs(None)) == [] and conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 1
    old = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    conn.execute("UPDATE submission_watch SET created_at=?", (old,)); conn.commit()
    w.poll_once(conn, FakeTabs(None))
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 0


def test_the_confirmation_email_finalizes_a_submit_even_when_the_tab_is_gone(tmp_path, monkeypatch):
    import time as _time
    conn = _setup(tmp_path); c = conn
    c.execute("INSERT INTO jobs (id, job_url, title, company, source, fetched_at) VALUES (7, 'u', 'Industrial Data Engineer', 'Thales', 'x', 'now')") if False else None
    _job(conn)
    c.execute("UPDATE jobs SET company='Thales', title='Industrial Data Engineer' WHERE id=7"); c.commit()
    w = SubmitWatcher(str(tmp_path / "t.db")); w.register(c, 7, "https://careers.thalesgroup.com/apply", "r", "TAB", how="auto")
    asked = []
    hit = {"subject": "Thank you for applying", "from": "recruiting@jobalerts.thalesgroup.com", "date": ""}
    check = lambda company, title, after: asked.append((company, title)) or hit
    assert w.poll_once(c, FakeTabs(None), check) == [] and asked == []              # too soon: a tab or a mail needs a couple of minutes
    c.execute("UPDATE submission_watch SET created_at=?", ((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),)); c.commit()
    assert w.poll_once(c, FakeTabs(None), check) == [7]                              # the tab was closed; the email proves it
    assert asked == [("Thales", "Industrial Data Engineer")]
    assert c.execute("SELECT status FROM jobs WHERE id=7").fetchone()[0] == "applied"
    assert c.execute("SELECT how FROM submit_history WHERE job_id=7").fetchone()[0] == "auto"
    # a miss asks again only after 5 minutes
    w.register(c, 7, "https://careers.thalesgroup.com/apply", "r", "TAB")
    c.execute("UPDATE submission_watch SET created_at=?", ((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),)); c.commit()
    w._last_email[7] = _time.time() - 10
    assert w.poll_once(c, FakeTabs(None), lambda *a: None) == [] and len(asked) == 1


class BlockedTab(FakeTab):
    def __init__(self, url, state, values=None, confirmed=(False, "no confirmation text")):
        super().__init__(url, values or {}, confirmed)
        self._state = state
    def blocked(self, board): return self._state


def _queued(conn, job_id=7, state="failed", reason="challenge"):
    conn.execute("INSERT INTO apply_queue (job_id, position, state, reason, added_at) VALUES (?,?,?,?,?)",
                 (job_id, 0.0, state, reason, "now")); conn.commit()


def test_a_block_the_human_has_not_cleared_keeps_the_watch_row(tmp_path):
    conn = _setup(tmp_path); _job(conn); _queued(conn)
    w = SubmitWatcher(str(tmp_path / "t.db"))
    w.register(conn, 7, "https://in.indeed.com/viewjob?jk=x", "r", "T", how="challenge")
    assert conn.execute("SELECT how FROM submission_watch WHERE job_id=7").fetchone()[0] == "challenge"
    assert w.poll_once(conn, FakeTabs(BlockedTab("https://in.indeed.com/viewjob?jk=x", "challenge"))) == []
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 1
    assert conn.execute("SELECT state FROM apply_queue WHERE job_id=7").fetchone()[0] == "failed"
    assert conn.execute("SELECT watch_cycles FROM apply_queue WHERE job_id=7").fetchone()[0] == 0


def test_clearing_the_block_on_the_tab_puts_the_job_back_in_the_queue(tmp_path):
    conn = _setup(tmp_path); _job(conn); _queued(conn)
    w = SubmitWatcher(str(tmp_path / "t.db"))
    w.register(conn, 7, "https://in.indeed.com/viewjob?jk=x", "r", "T", how="challenge")
    assert w.poll_once(conn, FakeTabs(BlockedTab("https://in.indeed.com/viewjob?jk=x", None))) == []
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 0
    assert conn.execute("SELECT state FROM apply_queue WHERE job_id=7").fetchone()[0] == "queued"
    assert conn.execute("SELECT watch_cycles FROM apply_queue WHERE job_id=7").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM jobs WHERE id=7").fetchone()[0] != "applied"


def test_a_cleared_block_that_also_proves_the_submit_marks_the_job_applied(tmp_path):
    conn = _setup(tmp_path); _job(conn); _queued(conn)
    w = SubmitWatcher(str(tmp_path / "t.db"))
    w.register(conn, 7, "https://in.indeed.com/viewjob?jk=x", "r", "T", how="gate:recaptcha_v2_checkbox")
    done = w.poll_once(conn, FakeTabs(BlockedTab("https://in.indeed.com/viewjob?jk=x", None,
                                                 confirmed=(True, "page says application submitted"))))
    assert done == [7]
    assert conn.execute("SELECT status FROM jobs WHERE id=7").fetchone()[0] == "applied"
    assert conn.execute("SELECT COUNT(*) FROM submit_history WHERE job_id=7").fetchone()[0] == 1


def test_no_entry_is_requeued_after_the_wait_and_three_cycles_cap_it(tmp_path):
    conn = _setup(tmp_path); _job(conn); _queued(conn, reason="no_entry")
    w = SubmitWatcher(str(tmp_path / "t.db"))
    w.register(conn, 7, "https://in.indeed.com/viewjob?jk=x", "r", None, how="no_entry")
    assert w.poll_once(conn, FakeTabs(None)) == []                                  # inside its 15-minute wait
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 1
    conn.execute("UPDATE submission_watch SET created_at=?",
                 ((datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat(),)); conn.commit()
    w.poll_once(conn, FakeTabs(None))
    assert conn.execute("SELECT state FROM apply_queue WHERE job_id=7").fetchone()[0] == "queued"
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 0
    conn.execute("UPDATE apply_queue SET watch_cycles=3 WHERE job_id=7"); conn.commit()
    w.register(conn, 7, "https://in.indeed.com/viewjob?jk=x", "r", None, how="no_entry")
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 0  # the cap: no more rows


def test_a_relaunch_from_the_watcher_skips_the_queue_row(tmp_path):
    conn = _setup(tmp_path); _job(conn); _queued(conn)
    w = SubmitWatcher(str(tmp_path / "t.db"), on_requeue=lambda job_id, url: True)
    w.register(conn, 7, "https://in.indeed.com/viewjob?jk=x", "r", "T", how="challenge")
    w.poll_once(conn, FakeTabs(BlockedTab("https://in.indeed.com/viewjob?jk=x", None)))
    assert conn.execute("SELECT state FROM apply_queue WHERE job_id=7").fetchone()[0] == "failed"
    assert conn.execute("SELECT watch_cycles FROM apply_queue WHERE job_id=7").fetchone()[0] == 1


def test_a_blocked_run_from_any_runner_is_discovered_from_run_log(tmp_path):
    conn = _setup(tmp_path); _job(conn); _queued(conn)
    for _ in range(3):                                                          # an older challenge before it
        conn.execute("INSERT INTO run_log (ts, url, job_id, stopped_reason) VALUES (?,?,?,?)",
                     ("2026-10-19T10:00:00", "u", 7, "challenge"))
    rs = ("2026-10-20T10:30:00", "https://in.indeed.com/viewjob?jk=x", 7, "challenge",
          '{"run_key": "kk", "final_tab_id": "T9"}')                            # the latest one counts
    conn.execute("INSERT INTO run_log (ts, url, job_id, stopped_reason, result_json) VALUES (?,?,?,?,?)", rs)
    conn.execute("INSERT INTO jobs (id, title, source, company, description, job_url, fetched_at) "
                 "VALUES (8, 'other', 'x', 'c', 'd', 'u8', 'now')"); conn.commit()  # a job whose latest run is fine
    conn.execute("INSERT INTO run_log (ts, url, job_id, stopped_reason) VALUES ('2026-10-20T11:00:00','u',8,'submitted')")
    w = SubmitWatcher(str(tmp_path / "t.db")); w.register_fresh_blocks(conn)
    row = conn.execute("SELECT url, run_key, tab_id, how FROM submission_watch WHERE job_id=7").fetchone()
    assert row == ("https://in.indeed.com/viewjob?jk=x", "kk", "T9", "challenge")
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 1  # job 8's submitted run not watched


def test_run_log_discovery_ignores_rows_already_queued_or_settled(tmp_path):
    conn = _setup(tmp_path); _job(conn)
    _queued(conn, state="queued", reason="challenge")
    conn.execute("INSERT INTO run_log (ts, url, job_id, stopped_reason) VALUES ('2026-10-20T10:00:00','u',7,'challenge')")
    conn.commit()
    w = SubmitWatcher(str(tmp_path / "t.db")); w.register_fresh_blocks(conn)
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 0
    conn.execute("UPDATE apply_queue SET state='failed' WHERE job_id=7")          # but once settled it stays watched off
    conn.execute("UPDATE jobs SET status='applied' WHERE id=7"); conn.commit()
    w.register_fresh_blocks(conn)
    assert conn.execute("SELECT COUNT(*) FROM submission_watch").fetchone()[0] == 0
