import sqlite3

from job_dashboard import autonomy, qa_store


def _db():
    c = sqlite3.connect(":memory:")
    qa_store.ensure(c)
    c.execute("CREATE TABLE qbank_entry (id TEXT PRIMARY KEY, answer TEXT)")
    c.execute("INSERT INTO qbank_entry VALUES ('notice_period','30 days'), ('current_ctc','25')")
    autonomy.ensure(c)
    return c


def _row(c, run, ref, label, answer, source, entry):
    qa_store.record(c, job_id=1, run_key=run, ref=ref, label=label, answer=answer, source=source, status="filled", retrieved_qkey=entry)


def test_unchanged_answers_earn_approvals_and_an_edit_resets_them():
    c = _db()
    for n in range(3):
        _row(c, f"r{n}", "#a", "Notice period", "30 days", "qbank", "notice_period")
        out = autonomy.record_submission(c, 1, f"r{n}", {"notice period": "30 days"}, "manual", "https://x.example/apply")
        assert out == {"approved": 1, "edited": 0}
    assert autonomy.approvals(c, "notice_period") == 3 and autonomy.is_autonomous_entry(c, "notice_period")
    _row(c, "r9", "#a", "Notice period", "30 days", "qbank", "notice_period")
    assert autonomy.record_submission(c, 1, "r9", {"notice period": "60 days"}, "manual") == {"approved": 0, "edited": 1}
    assert autonomy.approvals(c, "notice_period") == 0                                   # an edit resets to 0
    assert c.execute("SELECT outcome FROM application_qa WHERE run_key='r9'").fetchone()[0] == "edited"


def test_unreadable_fields_are_neither_approved_nor_edited_and_profile_sources_are_never_counted():
    c = _db()
    _row(c, "r", "#a", "Notice period", "30 days", "qbank", "notice_period")
    _row(c, "r", "#b", "Email", "a@b.co", "resume", None)
    out = autonomy.record_submission(c, 1, "r", {"email": "a@b.co"}, "manual")
    assert out == {"approved": 1, "edited": 0} and autonomy.approvals(c, "notice_period") == 0      # notice period unread; email is stable


def test_a_form_is_autonomous_only_when_every_answer_is():
    c = _db()
    c.execute("UPDATE qbank_entry SET approvals=3 WHERE id='notice_period'"); c.commit()
    _row(c, "r", "#a", "Notice period", "30 days", "qbank", "notice_period")
    _row(c, "r", "#b", "Current CTC", "25", "qbank", "current_ctc")
    base = [{"ref": "#e", "label": "Email", "value": "a@b.co", "source": "resume"},
            {"ref": "#a", "label": "Notice period", "value": "30 days", "source": "qbank"}]
    assert autonomy.autonomy_report(c, "r", base)["ok"]
    rep = autonomy.autonomy_report(c, "r", base + [{"ref": "#b", "label": "Current CTC", "value": "25", "source": "qbank"}])
    assert not rep["ok"] and rep["blockers"] == [("Current CTC", "current_ctc: 0/3 approvals")]
    assert not autonomy.autonomy_report(c, "r", base + [{"ref": "#z", "label": "Why us", "value": "…", "source": "qbank_likely"}])["ok"]
    assert not autonomy.autonomy_report(c, "r", base + [{"ref": "#y", "label": "Essay", "value": "…", "source": "judgment"}])["ok"]


def test_first_submit_on_a_new_kind_of_site_is_never_automatic():
    c = _db()
    assert autonomy.ats_key("https://www.linkedin.com/jobs/view/1/") == "linkedin.com"
    assert autonomy.ats_key("https://careers.thalesgroup.com/global/en/apply?x=1") == "careers.thalesgroup.com"
    assert not autonomy.has_confirmed_submit(c, "linkedin.com")
    autonomy.record_submission(c, 1, "none", {}, "manual", "https://www.linkedin.com/jobs/view/9/")
    assert autonomy.has_confirmed_submit(c, "linkedin.com") and not autonomy.has_confirmed_submit(c, "indeed.com")
    assert autonomy.auto_submits_last_day(c) == 0


def test_policy_needs_the_switch_autonomous_answers_a_history_on_that_site_and_cap_room():
    from job_dashboard.autonomy import autosubmit_policy
    c = _db()
    c.execute("UPDATE qbank_entry SET approvals=3 WHERE id='notice_period'"); c.commit()
    _row(c, "r", "#a", "Notice period", "30 days", "qbank", "notice_period")
    decisions = [{"ref": "#a", "label": "Notice period", "value": "30 days", "source": "qbank"},
                 {"ref": "#e", "label": "Email", "value": "a@b.co", "source": "resume"}]
    url = "https://careers.example.com/apply"
    p = autosubmit_policy(c, url, "r", decisions)
    assert not p["allow"] and any("auto-submit is off" in r for r in p["reasons"]) and any("first submit" in r for r in p["reasons"])
    qa_store.set_setting(c, "autosubmit_career_site", "1")
    assert any("first submit" in r for r in autosubmit_policy(c, url, "r", decisions)["reasons"])      # switch on, history still empty
    autonomy.record_submission(c, 1, "none", {}, "manual", url)                                        # you submitted there once
    assert autosubmit_policy(c, url, "r", decisions)["allow"]
    decisions.append({"ref": "#b", "label": "Current CTC", "value": "25", "source": "qbank"})
    _row(c, "r", "#b", "Current CTC", "25", "qbank", "current_ctc")
    p = autosubmit_policy(c, url, "r", decisions)
    assert not p["allow"] and "Current CTC (current_ctc: 0/3 approvals)" in p["reasons"][0]
    decisions.pop()
    qa_store.set_setting(c, "autosubmit_daily_cap", "1")
    autonomy.record_submission(c, 2, "none", {}, "auto", url)
    assert any("daily cap reached" in r for r in autosubmit_policy(c, url, "r", decisions)["reasons"])
