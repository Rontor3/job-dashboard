"""Auto-submit only forms with no blank/doubtful field; confident bank answers pass when trusted (2026-10-25)."""
import sqlite3
from job_dashboard import autonomy, qa_store


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE qbank_entry (id TEXT, approvals INTEGER)")
    qa_store.ensure(c); autonomy.ensure(c)
    return c


def test_a_blank_field_blocks_even_when_trusted():
    c = _conn()
    qa_store.set_setting(c, "autosubmit_trust_confident", "1")
    c.execute("INSERT INTO application_qa (run_key, ref, label, status) VALUES ('r','#a','Field of Study','needs_answer')")
    rep = autonomy.autonomy_report(c, "r", [{"ref": "#b", "label": "Name", "value": "x", "source": "qbank"}])
    assert not rep["ok"] and rep["blockers"][0][0] == "Field of Study"


def test_confident_bank_answers_pass_only_when_trusted():
    c = _conn()
    d = [{"ref": "#b", "label": "Notice", "value": "30", "source": "qbank"}]
    assert not autonomy.autonomy_report(c, "r", d)["ok"]
    qa_store.set_setting(c, "autosubmit_trust_confident", "1")
    assert autonomy.autonomy_report(c, "r", d)["ok"]
    assert not autonomy.autonomy_report(c, "r", [dict(d[0], source="qbank_likely")])["ok"]
