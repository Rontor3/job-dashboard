"""The mail gate: allowlisted senders, a bounded window, a second sender check, capped bodies, an audit log."""
import base64

import pytest

from job_dashboard import mail_gate
from job_dashboard.mail_gate import Gate, company_token, sender_allowed


class Gmail:
    def __init__(self, docs):
        self.docs, self.queries, self.fetched = docs, [], []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q, maxResults, pageToken=None):
        self.queries.append(q)
        return type("R", (), {"execute": lambda s: {"messages": [{"id": i} for i in self.docs]}})()

    def get(self, userId, id, format, metadataHeaders=None):
        self.fetched.append((id, format))
        d = self.docs[id]
        payload = {"headers": [{"name": "From", "value": d["from"]}, {"name": "Subject", "value": d["subject"]}]}
        if format == "full":
            payload |= {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(d["text"].encode()).decode()}}
        return type("R", (), {"execute": lambda s: {"id": id, "snippet": d["text"][:20], "internalDate": "0", "payload": payload}})()


@pytest.fixture(autouse=True)
def audit(tmp_path, monkeypatch):
    monkeypatch.setattr(mail_gate, "AUDIT", tmp_path / "mail-access.log")
    return tmp_path / "mail-access.log"


def test_sender_checks():
    assert sender_allowed("Greenhouse <no-reply@us.greenhouse-mail.io>", ["greenhouse-mail.io"])
    assert sender_allowed("Talent <jobs@razorpay.com>", ["razorpay"])
    assert sender_allowed("hr@careers.razorpay.co", ["razorpay"])
    assert not sender_allowed("Mom <mom@gmail.com>", ["greenhouse.io", "razorpay"])
    assert not sender_allowed("evil@greenhouse.io.attacker.net", ["greenhouse.io"])
    assert not sender_allowed("no address", ["greenhouse.io"])
    assert company_token("Razorpay Software Pvt Ltd") == "razorpay" and company_token("AI Labs") is None


def test_search_is_scoped_and_a_loose_match_is_refused_before_anything_is_returned(audit):
    svc = Gmail({"a": {"from": "jobs@lever.co", "subject": "Thanks for applying", "text": "code 123456"},
                 "b": {"from": "bank@hdfc.com", "subject": "Your statement", "text": "private"}})
    gate = Gate(svc, ["lever.co"], "otp", now=lambda: 100 * 86400)
    out = gate.search("subject:applying", since=0)
    assert [m["id"] for m in out] == ["a"]
    q = svc.queries[0]
    assert "{from:lever.co}" in q and f"after:{100 * 86400 - mail_gate.MAX_LOOKBACK_DAYS * 86400}" in q   # window floor
    assert gate.body("b") == "" and ("b", "full") not in svc.fetched                    # refused: never opened
    assert gate.body("a") == "code 123456"
    log = audit.read_text()
    assert "\totp\tb\thdfc.com\trefused" in log and "\totp\ta\tlever.co\tread" in log
    assert "statement" not in log and "123456" not in log                               # no subjects, bodies or codes


def test_no_allowlist_no_gate_and_no_way_to_change_mail():
    with pytest.raises(ValueError):
        Gate(Gmail({}), [], "x")
    assert not any(hasattr(Gate, m) for m in ("modify", "trash", "send", "mark_read"))


def test_bodies_are_capped():
    svc = Gmail({"a": {"from": "x@lever.co", "subject": "s", "text": "x" * 50_000}})
    gate = Gate(svc, ["lever.co"], "scan")
    gate.search()
    assert len(gate.body("a")) == mail_gate.MAX_BODY


def test_the_setting_adds_domains(tmp_path):
    from job_dashboard import qa_store
    from job_dashboard.db import init_db
    conn = init_db(str(tmp_path / "j.db"))
    qa_store.ensure(conn)
    qa_store.set_setting(conn, "mail_allowed_senders", " @Hiring.Example.com, foo.org ")
    senders = mail_gate.allowed_senders(conn, ["Razorpay"])
    assert {"hiring.example.com", "foo.org", "razorpay", "greenhouse.io"} <= set(senders)


def test_the_code_poller_reads_only_allowed_senders_and_never_prints_the_code(tmp_path, monkeypatch, capsys):
    from career_agent.integrations import gmail_otp
    token = tmp_path / "gmail_token.json"
    token.write_text("{}")
    svc = Gmail({"a": {"from": "Bank <otp@hdfcbank.net>", "subject": "OTP", "text": "Your OTP is 111111"},
                 "b": {"from": "no-reply@darwinbox.in", "subject": "Verify", "text": "Your code is 482913"}})
    monkeypatch.setattr(gmail_otp, "_TOKEN_PATH", token)
    monkeypatch.setattr(gmail_otp, "_build_service", lambda *a, **k: svc)
    assert gmail_otp.poll_otp(timeout_s=1, poll_interval_s=0) == "482913"
    assert ("a", "full") not in svc.fetched and all("is:unread after:" not in q or "{from:" in q for q in svc.queries)
    assert "482913" not in capsys.readouterr().out
