import time

from fastapi.testclient import TestClient

from job_dashboard import mail_scan, qa_store, tracker
from job_dashboard.api.app import create_app
from job_dashboard.api.mail_routes import MailScanner
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


class Box:
    def __init__(self, msgs):
        self.msgs = msgs

    def search(self, since):
        return self.msgs

    def body(self, mid):
        return "We would like to invite you to an interview, round 2."


MSG = {"id": "m1", "sender": "Acme <hr@acme.io>", "subject": "Interview invitation", "snippet": "invite",
       "received": int(time.time())}


def _client(tmp_path, box=MSG, connected=True):
    path = str(tmp_path / "t.db")
    conn = init_db(path)
    insert_job(conn, JobListing(source="s", title="ML", company="Acme", job_url="http://x/1", description="d"))
    tracker.set_status(conn, 1, "applied")
    conn.close()
    scanner = MailScanner(path, mailbox_factory=(lambda: Box([box])) if connected else (lambda: None),
                          llm=lambda p: '{"category": "interview", "round": 2, "summary": "invite"}')
    return TestClient(create_app(db_path=path, mail_scanner=scanner)), scanner, path


def test_scan_now_updates_the_job_and_lists_the_mail(tmp_path):
    c, scanner, _ = _client(tmp_path)
    r = c.post("/api/mail-scan")
    assert r.status_code == 200
    scanner._thread.join(timeout=5)
    st = c.get("/api/mail-scan/status").json()
    assert st["running"] is False and st["connected"] is True and st["last_result"]["matched"] == 1
    assert st["last_scan"] > 0
    mail = c.get("/api/jobs/1/mail").json()["mail"]
    assert mail[0]["category"] == "interview" and mail[0]["round"] == 2 and mail[0]["subject"] == "Interview invitation"
    assert c.get("/api/tracker").json()["interviewing"][0]["interview_round"] == 2


def test_scan_without_gmail_says_so(tmp_path):
    c, scanner, _ = _client(tmp_path, connected=False)
    c.post("/api/mail-scan")
    scanner._thread.join(timeout=5)
    st = c.get("/api/mail-scan/status").json()
    assert st["connected"] is False and st["last_result"]["error"] == "gmail_not_connected"


def test_a_second_scan_while_running_is_refused(tmp_path):
    c, scanner, _ = _client(tmp_path)
    import threading
    gate = threading.Event()
    scanner.mailbox_factory = lambda: (gate.wait(3), Box([MSG]))[1]
    assert c.post("/api/mail-scan").status_code == 200
    assert c.post("/api/mail-scan").status_code == 409
    gate.set()
    scanner._thread.join(timeout=5)


def test_daily_runner_scans_only_when_due(tmp_path):
    c, scanner, path = _client(tmp_path)
    assert scanner.run_if_due() is True
    scanner._thread.join(timeout=5)
    assert scanner.run_if_due() is False                    # scanned moments ago
    conn = init_db(path)
    qa_store.set_setting(conn, "mail_last_scan", int(time.time()) - 2 * 86400)
    assert scanner.run_if_due() is True
    scanner._thread.join(timeout=5)


def test_mail_for_a_job_with_none_is_an_empty_list(tmp_path):
    c, *_ = _client(tmp_path)
    assert c.get("/api/jobs/1/mail").json() == {"mail": []}
