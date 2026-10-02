from career_agent.memory import qbank
from career_agent.memory.learned_answers import ensure as ensure_learned
from career_agent.memory.qbank_admin import calibrate, migrate_learned


def test_migrate_keeps_good_rows_drops_junk(qbank_conn, fake_embed):
    ensure_learned(qbank_conn)
    rows = [("Notice period", "45"), ("Yes", "No"), ("cards[1][field3]", "Linkedin"),
            ("How would you rate your English language skills?", "Fluent"),
            ("Something odd entirely unrelated to anything?", "x")]
    for label, ans in rows:
        qbank_conn.execute("INSERT INTO learned_answers (qkey,label,answer,purpose,updated_at) "
                           "VALUES (?,?,?,NULL,'2026-01-01')", (qbank.norm(label), label, ans))
    r = migrate_learned(qbank_conn, fake_embed)
    assert r["junk"] == ["Yes", "cards[1][field3]"]
    assert r["unmatched"] == ["Something odd entirely unrelated to anything?"]
    assert set(r["migrated"]) == {"Notice period", "How would you rate your English language skills?"}
    assert qbank.get_entry(qbank_conn, "notice_period")["answer"] == "30"          # never overwritten
    assert qbank.get_entry(qbank_conn, "english_proficiency")["answer"] == "Fluent"  # filled when empty


def test_calibrate_reports_accuracy_and_suggestions(qbank_conn, fake_embed):
    r = calibrate(qbank_conn, fake_embed, negatives=["Describe your favourite hobby outside work"])
    assert r["evaluated"] >= 6 and 0 <= r["top1_accuracy"] <= 1
    assert set(r["suggested"]) == {"FLOOR", "HIGH", "MARGIN"}
