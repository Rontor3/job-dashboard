"""'Mention your previous company?' is the job before this one (Lingaro on Lever, 2026-11-01: got Tata AIG)."""
from types import SimpleNamespace as N

from career_agent.browser.form_model import Field
from career_agent.orchestrator.screen_review import map_screen

PROF = N(experiences=[N(company="Tata AIG", title="Data Scientist", start="July 2023", end="Present"),
                      N(company="OYO (Internship)", title="Data Science Intern", start="May 2022", end="Jul 2022")],
         education=[], skills=[], contact={})


def test_previous_company_is_the_second_job_and_current_stays_the_first():
    fs = [Field("#p", "text", "Mention your previous company?", True, purpose="employer"),
          Field("#c", "text", "Current company", True, purpose="employer"),
          Field("#y", "text", "Employer in the last 5 years", True, purpose="employer")]
    decisions, _ = map_screen(fs, PROF)
    got = {d.ref: d.value for d in decisions}
    assert got["#p"] == "OYO" and got["#c"] == "Tata AIG" and got["#y"] == "Tata AIG"


def test_the_bank_does_not_answer_previous_with_the_saved_current_employer():
    import sqlite3
    from career_agent.memory import qbank
    from career_agent.memory.qbank_match import answer_field
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    qbank.ensure(conn)
    qbank.upsert_entry(conn, {"id": "current_employer", "question": "Mention your current company?", "topic": "work", "atype": "text"})
    qbank.set_answer(conn, "current_employer", "TATA AIG")
    same = lambda texts: [[1.0, 0.0]] * len(texts)          # every wording reads the same: only the guard tells them apart
    qbank.add_wording(conn, "Mention your current company?", "current_employer", same(["x"])[0], "user")
    prev = Field("#p", "textarea", "Mention your previous company?*", True, purpose="employer")
    m, v = answer_field(conn, prev, embed=same)
    assert m.entry_id is None and v is None
    cur = Field("#c", "textarea", "Mention your current company?*", True, purpose="employer")
    assert answer_field(conn, cur, embed=same)[1] == "TATA AIG"
