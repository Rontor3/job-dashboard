import json
import sqlite3

from career_agent.memory import qbank
from career_agent.memory.learned_answers import ensure as ensure_learned
from career_agent.memory.qbank_admin import MERGES, RETIRE, calibrate, cleanup, merge_entry, migrate_learned


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


def _two(c, fake_embed):
    for i in ("a", "b"):
        qbank.upsert_entry(c, {"id": i, "question": f"q {i}", "atype": "text"})
    qbank.add_wording(c, "Old wording?", "a", fake_embed(["Old wording?"])[0], "seed")


def test_merge_moves_wordings_and_supersedes(qbank_conn, fake_embed):
    _two(qbank_conn, fake_embed)
    assert merge_entry(qbank_conn, "a", "b") == 1
    assert qbank.exact(qbank_conn, "Old wording?") == "b"
    assert qbank.get_entry(qbank_conn, "a")["status"] == "superseded"
    assert merge_entry(qbank_conn, "a", "b") == 0                    # idempotent
    assert merge_entry(qbank_conn, "nope", "b") == 0 and merge_entry(qbank_conn, "b", "nope") == 0


def test_cleanup_on_real_seed(fake_embed):
    c = sqlite3.connect(":memory:")
    qbank.ensure(c)
    raw = json.loads(qbank.SEED_PATH.read_text())["entries"]
    ids = {e["id"] for e in raw}
    assert {d for _, d in MERGES} <= ids                              # survivors are in the seed
    assert not ({s for s, _ in MERGES} | set(RETIRE)) & ids           # removed ones are gone from the seed
    for e in raw:
        qbank.upsert_entry(c, e)
    for s in [s for s, _ in MERGES] + RETIRE:                         # simulate a DB seeded before this change
        qbank.upsert_entry(c, {"id": s, "question": s, "atype": "text"})
    r = cleanup(c)
    assert r["merged"] == len(MERGES) and r["retired"] == len(RETIRE)
    assert all(qbank.get_entry(c, s)["status"] == "superseded" for s, _ in MERGES)
    assert cleanup(c) == {"merged": 0, "retired": 0}                  # idempotent
