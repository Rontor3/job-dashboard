import time

from job_dashboard import mail_scan, qa_store, tracker
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


class Box:
    """Fake mailbox: search(since) -> metadata dicts, body(id) -> text."""

    def __init__(self, msgs):
        self.msgs = msgs
        self.bodies_read = []
        self.since = None

    def search(self, since_epoch):
        self.since = since_epoch
        return [{k: v for k, v in m.items() if k != "body"} for m in self.msgs]

    def body(self, msg_id):
        self.bodies_read.append(msg_id)
        return next(m["body"] for m in self.msgs if m["id"] == msg_id)


def msg(i, sender, subject, body="", received=None):
    return {"id": f"m{i}", "sender": sender, "subject": subject, "snippet": body[:80], "body": body,
            "received": received or int(time.time())}


def llm_says(category, round_=None):
    return lambda p: f'{{"category": "{category}", "round": {round_ if round_ else "null"}, "summary": "s"}}'


def _db(tmp_path, jobs):
    conn = init_db(str(tmp_path / "t.db"))
    ids = {}
    for i, (company, title, status) in enumerate(jobs):
        insert_job(conn, JobListing(source="s", title=title, company=company, job_url=f"http://x/{i}", description="d"))
        jid = conn.execute("SELECT id FROM jobs WHERE job_url = ?", (f"http://x/{i}",)).fetchone()[0]
        tracker.set_status(conn, jid, status)
        ids[company + "|" + title] = jid
    return conn, ids


def _status(conn, jid):
    return conn.execute("SELECT status, interview_round FROM jobs WHERE id = ?", (jid,)).fetchone()


def test_company_name_in_sender_or_subject_matches_and_classification_moves_the_job(tmp_path):
    conn, ids = _db(tmp_path, [("Acme AI Pvt Ltd", "ML Engineer", "applied"), ("Globex", "SWE", "applied")])
    box = Box([msg(1, "Acme AI Careers <talent@acmeai.com>", "Interview invitation", "Round 2 is on Friday"),
               msg(2, "Mom <mom@gmail.com>", "Dinner?", "Globex stock tips"),
               msg(3, "noreply@somesite.com", "Weekly digest", "nothing")])
    out = mail_scan.run_scan(conn, box, llm_says("interview", 2), now=1_000_000)
    assert out["matched"] == 1 and out["scanned"] == 3
    assert _status(conn, ids["Acme AI Pvt Ltd|ML Engineer"]) == ("interviewing", 2)
    assert _status(conn, ids["Globex|SWE"]) == ("applied", None)
    assert box.bodies_read == ["m1"]                      # unmatched mail is never opened
    ch = out["changes"][0]
    assert (ch["company"], ch["category"], ch["status"]) == ("Acme AI Pvt Ltd", "interview", "interviewing")


def test_rejection_and_offer_set_final_statuses_and_final_states_stick(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "A", "interviewing"), ("Globex", "B", "interviewing")])
    box = Box([msg(1, "Acme HR <hr@acme.io>", "Update", "We regret to inform you"),
               msg(2, "Globex <jobs@globex.com>", "Offer", "We are pleased to offer")])
    mail_scan.run_scan(conn, box, llm_says("rejected"), now=1)
    assert _status(conn, ids["Acme|A"])[0] == "rejected" and _status(conn, ids["Globex|B"])[0] == "rejected"
    box2 = Box([msg(3, "Acme HR <hr@acme.io>", "Interview again", "round 3")])
    mail_scan.run_scan(conn, box2, llm_says("interview", 3), now=2)
    assert _status(conn, ids["Acme|A"])[0] == "rejected"      # a later mail never revives a rejection


def test_offer_maps_to_selected(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "A", "interviewing")])
    mail_scan.run_scan(conn, Box([msg(1, "Acme <hr@acme.io>", "Offer", "x")]), llm_says("offer"), now=1)
    assert _status(conn, ids["Acme|A"])[0] == "offer"


def test_rescanning_the_same_mail_is_a_no_op_and_rounds_never_go_down(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "A", "interviewing")])
    tracker.set_status(conn, ids["Acme|A"], "interviewing", round=3)
    box = Box([msg(1, "Acme <hr@acme.io>", "Interview", "round 2 details")])
    first = mail_scan.run_scan(conn, box, llm_says("interview", 2), now=1)
    second = mail_scan.run_scan(conn, box, llm_says("interview", 2), now=2)
    assert first["matched"] == 1 and second["matched"] == 0
    assert _status(conn, ids["Acme|A"]) == ("interviewing", 3)
    assert len(mail_scan.mail_for_job(conn, ids["Acme|A"])) == 1


def test_first_interview_mail_for_an_applied_job_is_round_one(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "A", "applied")])
    mail_scan.run_scan(conn, Box([msg(1, "Acme <hr@acme.io>", "Interview", "let's talk")]), llm_says("interview"), now=1)
    assert _status(conn, ids["Acme|A"]) == ("interviewing", 1)


def test_same_company_two_jobs_goes_to_the_title_named_in_the_subject(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "Data Scientist", "applied"), ("Acme", "Backend Engineer", "applied")])
    mail_scan.run_scan(conn, Box([msg(1, "Acme <hr@acme.io>", "Backend Engineer – interview", "x")]),
                       llm_says("interview"), now=1)
    assert _status(conn, ids["Acme|Backend Engineer"])[0] == "interviewing"
    assert _status(conn, ids["Acme|Data Scientist"])[0] == "applied"


def test_the_first_company_mail_saves_its_sender_and_later_mail_from_it_matches_without_the_name(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "A", "applied")])
    mail_scan.run_scan(conn, Box([msg(1, "Acme <no-reply@hire.acme.io>", "Application received", "thanks")]),
                       llm_says("acknowledgement"), now=1)
    assert mail_scan.sender_for_job(conn, ids["Acme|A"]) == "no-reply@hire.acme.io"
    out = mail_scan.run_scan(conn, Box([msg(2, "no-reply@hire.acme.io", "Your next step", "pls book a slot")]),
                             llm_says("interview"), now=2)
    assert out["matched"] == 1 and _status(conn, ids["Acme|A"])[0] == "interviewing"


def test_job_board_mail_only_counts_when_it_carries_a_decision(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "A", "applied")])
    box = Box([msg(1, "Naukri <info@naukri.com>", "Acme is hiring more roles", "jobs you may like"),
               msg(2, "Naukri <updates@naukri.com>", "Acme application update", "not moving forward")])
    out = mail_scan.run_scan(conn, box, llm_says("other"), now=1)
    assert out["matched"] == 0 and mail_scan.sender_for_job(conn, ids["Acme|A"]) is None
    out = mail_scan.run_scan(conn, Box([msg(3, "Naukri <updates@naukri.com>", "Acme application update", "x")]),
                             llm_says("rejected"), now=2)
    assert out["matched"] == 1 and _status(conn, ids["Acme|A"])[0] == "rejected"
    assert mail_scan.sender_for_job(conn, ids["Acme|A"]) is None       # never remember a job board as the company


def test_only_applied_and_interviewing_jobs_are_scanned(tmp_path):
    conn, ids = _db(tmp_path, [("Acme", "A", "saved"), ("Globex", "B", "failed")])
    out = mail_scan.run_scan(conn, Box([msg(1, "Acme <hr@acme.io>", "Interview", "x"),
                                        msg(2, "Globex <hr@globex.com>", "Interview", "x")]), llm_says("interview"), now=1)
    assert out["matched"] == 0


def test_scan_window_and_clock_are_remembered(tmp_path):
    conn, _ = _db(tmp_path, [("Acme", "A", "applied")])
    box = Box([])
    mail_scan.run_scan(conn, box, None, now=100 * 86400)
    assert box.since == 70 * 86400                                   # first scan: 30-day lookback
    box2 = Box([])
    mail_scan.run_scan(conn, box2, None, now=101 * 86400)
    assert box2.since == 99 * 86400                                  # then from the last scan, overlapping a day
    assert qa_store.get_setting(conn, "mail_last_scan") == str(101 * 86400)


def test_due_only_after_a_day_and_never_when_gmail_is_not_connected(tmp_path):
    conn, _ = _db(tmp_path, [("Acme", "A", "applied")])
    assert mail_scan.is_due(conn, now=1_000_000)
    qa_store.set_setting(conn, "mail_last_scan", 1_000_000)
    assert not mail_scan.is_due(conn, now=1_000_000 + 3600)
    assert mail_scan.is_due(conn, now=1_000_000 + 86400 + 1)
    out = mail_scan.run_scan(conn, None, None, now=5)
    assert out["error"] == "gmail_not_connected" and out["matched"] == 0


def test_a_failing_mailbox_reports_an_error_and_keeps_the_old_scan_time(tmp_path):
    conn, _ = _db(tmp_path, [("Acme", "A", "applied")])

    class Broken:
        def search(self, since):
            raise OSError("network")

    out = mail_scan.run_scan(conn, Broken(), None, now=77)
    assert out["error"] == "OSError" and qa_store.get_setting(conn, "mail_last_scan") == "0"


class FakeGmail:
    """Just enough of googleapiclient: users().messages().list/get(...).execute()."""

    def __init__(self, pages, messages):
        self.pages, self.docs, self.queries = pages, messages, []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q, maxResults, pageToken=None):
        self.queries.append(q)
        page = self.pages[0 if pageToken is None else int(pageToken)]
        resp = {"messages": [{"id": i} for i in page]}
        if pageToken is None and len(self.pages) > 1:
            resp["nextPageToken"] = "1"
        return type("R", (), {"execute": lambda s: resp})()

    def get(self, userId, id, format, metadataHeaders=None):
        import base64
        m = self.docs[id]
        payload = {"headers": [{"name": "From", "value": m["from"]}, {"name": "Subject", "value": m["subject"]}]}
        if format == "full":
            data = base64.urlsafe_b64encode(m["text"].encode()).decode()
            payload = {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/html", "body": {"data": ""}},
                {"mimeType": "multipart/mixed", "parts": [{"mimeType": "text/plain", "body": {"data": data}}]}]}
        resp = {"id": id, "snippet": m["text"][:40], "internalDate": "1700000000000", "payload": payload}
        return type("R", (), {"execute": lambda s: resp})()


def test_gmail_adapter_pages_reads_headers_and_nested_plaintext():
    svc = FakeGmail([["a"], ["b"]], {"a": {"from": "Acme <hr@acme.io>", "subject": "Hi", "text": "round 2 on friday"},
                                     "b": {"from": "x@y.com", "subject": "Yo", "text": "hello"}})
    box = mail_scan.GmailMailbox(svc)
    msgs = box.search(1234)
    assert [m["id"] for m in msgs] == ["a", "b"]
    assert msgs[0]["sender"] == "Acme <hr@acme.io>" and msgs[0]["subject"] == "Hi" and msgs[0]["received"] == 1_700_000_000
    assert "after:1234" in svc.queries[0] and "-from:me" in svc.queries[0]
    assert box.body("a") == "round 2 on friday"
