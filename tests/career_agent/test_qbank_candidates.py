"""Candidate B (closed feedback loop): every human-typed answer proposes a
qbank_candidate; only the operator's `scripts/qbank.py curate` closes it into
the bank — through the same path a human answer enters today, behind the
red-team guards. Also D-lite: the decline/held rows carry a policy_verdict.
See docs/career-agent/triage/answer-pipeline-analysis.md §4 B / answer-redteam.md
§B-1, B-2, §5 (approvals bootstrap deferred; no bulk import)."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from career_agent.browser.form_model import Field
from career_agent.memory import qbank
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator import decline_class as dc
from career_agent.orchestrator.answering import answer_fields
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.qa_recorder import QARecorder
from job_dashboard import autonomy, qa_store
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing

P = CandidateProfile(contact={})
CLI_PATH = Path(__file__).resolve().parents[2] / "scripts" / "qbank.py"


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "t.db"))
    qbank.ensure(c)     # how a reply path sees jobs.db: qa_routes.db()/QBankMemory create the bank too
    for n in (1, 2):    # two jobs so the curate list shows where each answer came from
        insert_job(c, JobListing(source="s", title=f"T{n}", company=f"C{n}",
                                 job_url=f"https://x/{n}", description="jd"))
    yield c
    c.close()


def _new_conn(tmp_path, name) :
    c = init_db(str(tmp_path / name))
    qbank.ensure(c)
    return c


def _ask(conn, job_id, label, run="r1", ref="#a", source=None):
    """A run asked the question and nobody answered yet."""
    qa_store.record(conn, job_id=job_id, run_key=run, ref=ref, label=label,
                    kind="text", status="needs_answer", **({"source": source} if source else {}))
    return qa_store.norm_key(label)


def _reply(conn, job_id, label, answer, run="r1", ref="#a"):
    _ask(conn, job_id, label, run=run, ref=ref)
    return qa_store.mark_answered(conn, job_id, qa_store.norm_key(label), answer)


def _pending(conn):
    return [(c["id"], c["qkey"], c["answer"]) for c in qa_store.pending_candidates(conn)]


def _insert(conn, *, label, answer, question=None, qkey=None, kind="text"):
    """A candidate row as a writer could have left it (edge cases the reply path skips)."""
    qa_store.ensure(conn)
    question = question or label
    qkey = qkey or qa_store.norm_key(question)
    cur = conn.execute(
        "INSERT INTO qbank_candidate (job_id, qkey, label, question_text, answer, kind, source, created_at) "
        "VALUES (1, ?, ?, ?, ?, ?, 'human', ?)", (qkey, label, question, answer, kind, qa_store._now()))
    conn.commit()
    return cur.lastrowid


# ── the write hook: every human reply proposes ───────────────────────────────

def test_a_tracker_reply_proposes_one_pending_candidate(conn):
    _reply(conn, 1, "Notice period?", "30 days")
    (cid, qkey, answer), = _pending(conn)
    assert answer == "30 days"
    row = qa_store.candidate(conn, cid)
    assert (row["label"], row["question_text"], row["kind"], row["source"], row["status"]) == \
        ("Notice period?", "Notice period?", "text", "human", "pending")
    assert row["qkey"] == qa_store.norm_key("Notice period?")


def test_the_same_reply_twice_is_one_candidate_and_a_new_answer_is_one_more(conn):
    assert _reply(conn, 1, "Notice period?", "30 days", run="r1") == 1
    assert _reply(conn, 1, "Notice period?", "30 days", run="r2") == 1   # re-run asked again, same answer
    assert len(_pending(conn)) == 1                                      # UNIQUE(qkey, answer): still one proposal
    assert _reply(conn, 1, "Notice period?", "60 days", run="r3") == 1   # the human changed the value
    assert [a for _, _, a in _pending(conn)] == ["30 days", "60 days"]


def test_bank_sourced_and_judged_lanes_propose_nothing(conn):
    # memory/judge/gate fills are recorded by the run itself — no mark_answered, no proposal
    qa_store.record(conn, job_id=1, run_key="r1", ref="#q", label="LinkedIn profile URL",
                    kind="text", answer="https://x", source="qbank", status="filled")
    qa_store.record(conn, job_id=1, run_key="r1", ref="#w", label="Notice period",
                    kind="text", answer="30", source="qbank_likely", status="filled")
    qa_store.record(conn, job_id=1, run_key="r1", ref="#j", label="Why us?",
                    kind="textarea", answer="...", source="judgment", status="filled")
    assert _pending(conn) == []


def test_a_confirmed_bank_guess_reply_is_a_human_decision_and_proposes(conn):
    k = _ask(conn, 1, "Notice period?", source="qbank_likely")
    qa_store.mark_answered(conn, 1, k, "30 days", keep_source=True)     # the human re-typed the guess
    assert [a for _, _, a in _pending(conn)] == ["30 days"]             # a human decision is bank-worthy


def test_the_telegram_reply_proposes_when_the_bank_did_not_take_it(conn, tmp_path):
    rec = QARecorder(_new_conn(tmp_path, "r.db"), job_id=5)             # no promote_embed set
    rec.answered(Field("#q", "text", "Are you comfortable with on-call rotations?", True, [], None, None), "Yes")
    assert len(_pending(rec.conn)) == 1 and qbank.entries(rec.conn) == []


def test_answered_by_the_bank_lands_in_the_bank_and_proposes_no_duplicate(conn, tmp_path, fake_embed):
    rec = QARecorder(_new_conn(tmp_path, "r.db"), job_id=5)
    rec.promote_embed = fake_embed
    rec.answered(Field("#q", "text", "Notice period?", True, [], None, None), "30 days")
    assert _pending(rec.conn) == [] and len(qbank.entries(rec.conn)) == 1   # the bank already has it


def test_candidates_never_touch_the_answer_stats_or_autonomy_lanes(conn, fake_embed):
    _reply(conn, 1, "Notice period?", "30 days")
    cid, = [i for i, _, _ in _pending(conn)]
    snap = (qa_store.open_counts(conn), qa_store.asked_in_counts(conn), qa_store.retrieval_stats(conn),
            qa_store.applications_for(conn, qa_store.norm_key("Notice period?")))
    r = qa_store.promote_candidate(conn, cid, fake_embed)
    assert r["promoted"] and _pending(conn) == []
    assert (qa_store.open_counts(conn), qa_store.asked_in_counts(conn), qa_store.retrieval_stats(conn),
            qa_store.applications_for(conn, qa_store.norm_key("Notice period?"))) == snap   # stats lanes never noticed
    autonomy.ensure(conn)
    assert autonomy.autonomy_report(conn, "r1", []) == {"ok": True, "blockers": [], "confident": 0, "total": 0}


def test_a_bank_entry_with_an_answer_stops_proposals_until_its_empty_again(conn, fake_embed):
    eid = qbank.add_entry(conn, question="Notice period?", kind="text", answer="30", embed=fake_embed)
    _reply(conn, 1, "Notice period?", "60 days")
    assert _pending(conn) == []                     # the bank holds an answer; a proposal could only zombie
    qbank.set_answer(conn, eid, None)               # the dashboard emptied the entry: a reply is bankable again
    _reply(conn, 1, "Notice period?", "60 days", run="r2")
    assert [a for _, _, a in _pending(conn)] == ["60 days"]


def test_a_failing_proposal_never_breaks_the_reply(conn, monkeypatch):
    monkeypatch.setattr(qa_store, "propose_candidate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    _ask(conn, 1, "Why us?")
    assert qa_store.mark_answered(conn, 1, qa_store.norm_key("Why us?"), "because") == 1
    assert qa_store.open_questions(conn, 1) == []


# ── curate: promote through the normal human-answer path, reject ────────────

def test_curate_approve_uses_the_normal_human_answer_path(conn, fake_embed):
    _reply(conn, 2, "Notice period?", "30 days")
    (cid, _, _), = _pending(conn)
    c = qa_store.candidate(conn, cid)
    assert (c["job_id"], c["title"], c["company"]) == (2, "T2", "C2")    # the source job is in the list
    r = qa_store.promote_candidate(conn, cid, fake_embed)
    assert r["promoted"]
    eid = r["entry_id"]
    assert qbank.exact(conn, "Notice period?") == eid                   # the bank's normal read path finds it
    assert qbank.get_entry(conn, eid)["answer"] == "30 days"
    assert "Notice period?" in qbank.wordings_for(conn, eid)
    autonomy.ensure(conn)
    assert autonomy.approvals(conn, eid) == 0                           # approvals bootstrap stays deferred
    row = qa_store.candidate(conn, cid)
    assert row["status"] == "approved" and eid in row["notes"] and row["decided_at"]
    assert _pending(conn) == []


def test_curate_approve_never_overwrites_a_borrowed_wording(conn, fake_embed):
    """Track the same wording to an existing entry: promote_answer fills only an EMPTY entry."""
    eid = qbank.add_entry(conn, question="Notice period?", kind="text", answer="45", embed=fake_embed)
    _reply(conn, 1, "Notice period?", "30 days")
    assert _pending(conn) == []                                          # dedupe kept it out (bank answered)
    qbank.set_answer(conn, eid, None)
    _reply(conn, 1, "Notice period?", "30 days", run="r2")
    cid, = [i for i, _, _ in _pending(conn)]
    r = qa_store.promote_candidate(conn, cid, fake_embed)
    assert r["promoted"] and r["entry_id"] == eid                        # prompted into the SAME entry
    assert qbank.wordings_for(conn, eid).count("Notice period?") == 1    # dedupe, not a second wording


def test_curate_reject_marks_the_row_and_leaves_the_bank_alone(conn, fake_embed):
    _reply(conn, 1, "What is your hometown?", "Mumbai")
    cid, = [i for i, _, _ in _pending(conn)]
    assert qa_store.set_candidate_status(conn, cid, "rejected", "kept out by hand")
    assert _pending(conn) == [] and len(qbank.entries(conn)) == 0
    row = qa_store.candidate(conn, cid)
    assert row["status"] == "rejected" and row["notes"] == "kept out by hand" and row["decided_at"]
    assert qa_store.set_candidate_status(conn, cid, "approved") is False   # decided rows don't flip
    with pytest.raises(ValueError):
        qa_store.set_candidate_status(conn, cid, "pending")
    assert qa_store.promote_candidate(conn, cid, fake_embed)["reason"].endswith("rejected, not pending")


# ── the promote guards (red-team §5) ─────────────────────────────────────────

@pytest.mark.parametrize("label,answer,fragment", [
    ("Have you previously worked for MKS Inc?", "No", "boolean-ambiguous"),        # B-1 poison class
    ("Country Phone Code*", "+91", "phone shape"),                                 # 30901: a dial code is not a phone value
])
def test_guarded_candidates_are_rejected_with_the_printed_reason(conn, fake_embed, label, answer, fragment):
    _reply(conn, 1, label, answer)
    cid, = [i for i, _, _ in _pending(conn)]
    r = qa_store.promote_candidate(conn, cid, fake_embed)
    assert r["promoted"] is False and fragment in r["reason"]
    row = qa_store.candidate(conn, cid)
    assert row["status"] == "rejected" and fragment in row["notes"] and row["decided_at"]
    assert qbank.entries(conn) == []


def test_empty_and_tampered_candidates_are_rejected(conn, fake_embed):
    r = qa_store.promote_candidate(conn, _insert(conn, label="Notice period?", answer="   "), fake_embed)
    assert "empty answer" in r["reason"]
    r = qa_store.promote_candidate(conn, _insert(conn, label="Notice period?", answer="30 days",
                                                 question="Notice period?", qkey="someone else"), fake_embed)
    assert "does not normalize to its key" in r["reason"]           # exact-normalized question matching
    assert qbank.entries(conn) == []


@pytest.mark.parametrize("label,answer", [
    ("Is your mobile number on file?", "+91 9876501234"),
    ('Where is your current location? If relocating, type "relocating".', "Pune"),
])
def test_valid_values_and_peeled_escape_sentences_promote(conn, fake_embed, label, answer):
    _reply(conn, 1, label, answer)
    cid, = [i for i, _, _ in _pending(conn)]
    r = qa_store.promote_candidate(conn, cid, fake_embed)
    assert r["promoted"], r["reason"]
    eid = r["entry_id"]
    assert qbank.get_entry(conn, eid)["answer"] == answer
    assert "type" not in qbank.get_entry(conn, eid)["question"]         # escape sentence peeled by the normal path


def test_company_specific_essays_are_rejected_by_the_bank_path(conn, fake_embed):
    _reply(conn, 1, "Why do you want to join Acme?", "Because agents")
    cid, = [i for i, _, _ in _pending(conn)]
    r = qa_store.promote_candidate(conn, cid, fake_embed)
    assert r["promoted"] is False and "company-specific" in r["reason"]
    assert qbank.entries(conn) == []


# ── the curate CLI ───────────────────────────────────────────────────────────

def _cli():
    spec = importlib.util.spec_from_file_location("qbank_curate_cli", CLI_PATH)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def test_curate_cli_lists_approves_and_rejects(tmp_path, fake_embed, monkeypatch, capsys):
    c = init_db(str(tmp_path / "c.db"))
    qbank.ensure(c)
    for n in (1, 2):
        insert_job(c, JobListing(source="s", title=f"T{n}", company=f"C{n}",
                                 job_url=f"https://x/{n}", description="jd"))
    _reply(c, 1, "Notice period?", "30 days")
    _reply(c, 2, "What is your hometown?", "Mumbai", ref="#b")
    ids = [i for i, _, _ in _pending(c)]
    assert ids == [1, 2]
    c.commit()
    c.close()
    monkeypatch.setattr(qbank, "default_embed", fake_embed)             # main() embeds through this name
    monkeypatch.setattr(sys, "argv", ["qbank.py", "--db", str(tmp_path / "c.db"), "curate"])
    _cli().main()
    out = capsys.readouterr().out
    assert "2 pending candidate(s)" in out
    assert "Notice period?" in out and "C1: T1" in out                  # id, question, source job
    monkeypatch.setattr(sys, "argv", ["qbank.py", "--db", str(tmp_path / "c.db"), "curate",
                                      "--reject", "1", "--note", "wrong question"])
    _cli().main()
    assert "candidate 1: rejected" in capsys.readouterr().out
    conn = sqlite3.connect(tmp_path / "c.db")
    assert conn.execute("SELECT status, notes FROM qbank_candidate WHERE id=?", (1,)).fetchone() == \
        ("rejected", "wrong question")
    conn.close()
    monkeypatch.setattr(sys, "argv", ["qbank.py", "--db", str(tmp_path / "c.db"), "curate"])
    _cli().main()
    assert "1 pending candidate(s)" in capsys.readouterr().out          # the rejected row left the list


def test_curate_cli_approve_promotes_through_the_guard(conn, tmp_path, fake_embed, monkeypatch, capsys):
    c = init_db(str(tmp_path / "c.db"))
    _reply(c, 1, "Have you previously worked for MKS Inc?", "No")       # guard must refuse
    cid, = [i for i, _, _ in _pending(c)]
    c.commit()
    c.close()
    monkeypatch.setattr(qbank, "default_embed", fake_embed)
    monkeypatch.setattr(sys, "argv", ["qbank.py", "--db", str(tmp_path / "c.db"), "curate", "--approve", str(cid)])
    _cli().main()
    out = capsys.readouterr().out
    assert f"candidate {cid}: rejected — boolean-ambiguous" in out.splitlines()[0]


# ── D-lite: policy_verdict on the gate's rows ────────────────────────────────

def test_the_recorder_writes_the_policy_verdicts(tmp_path):
    conn = init_db(str(tmp_path / "v.db"))
    rec = QARecorder(conn, 3)
    rec.decision(FillDecision("#n", "text", "Notice period?", "30 days", "fill", "recall"))
    rec.decision(FillDecision("#m", "checkbox", "Get email updates for the latest jobs", False,
                              "uncheck", dc.SOURCE, basis=f"{dc.DECLINE_BASIS} (test)"))
    rec.held(Field("#h", "checkbox", "I consent to receive update messages by email", True, [], None, None),
             basis="required marketing opt-in held back")
    rows = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT ref, policy_verdict, status FROM application_qa")}
    assert rows["#n"] == (None, "filled") and rows["#m"] == ("decline", "filled")
    assert rows["#h"] == ("held-required", "held")


def test_answer_fields_records_the_verdict_on_the_gate_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")
    qa_store.ensure(conn)
    ctx = {"profile": P, "qa": QARecorder(conn, 7, run_key="run")}
    fields = [Field("#m", "checkbox", "Get email updates for the latest senior data scientist jobs",
                    False, [], None, None),
              Field("#r", "checkbox", "I consent to receive update messages by email", True, [], None, None)]
    decisions, needs = answer_fields(fields, ctx)
    assert [(d.ref, d.source) for d in decisions] == [("#m", dc.SOURCE)]
    assert [f.ref for f in needs] == ["#r"]
    rows = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT ref, policy_verdict, status FROM application_qa")}
    assert rows["#m"] == ("decline", "filled")
    assert rows["#r"] == ("held-required", "needs_answer")              # held, then asked at the escalation boundary
