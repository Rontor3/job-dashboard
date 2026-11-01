"""'Mention your previous company?' is the job before this one (Lingaro on Lever, 2026-11-01: got Tata AIG)."""
from types import SimpleNamespace as N

from career_agent.browser.form_model import Field
from career_agent.orchestrator.screen_review import map_screen

PROF = N(experiences=[N(company="Tata AIG", title="Data Scientist", start="July 2023", end="Present"),
                      N(company="OYO", title="Data Science Intern", start="May 2022", end="Jul 2022")],
         education=[], skills=[], contact={})


def test_previous_company_is_the_second_job_and_current_stays_the_first():
    fs = [Field("#p", "text", "Mention your previous company?", True, purpose="employer"),
          Field("#c", "text", "Current company", True, purpose="employer"),
          Field("#y", "text", "Employer in the last 5 years", True, purpose="employer")]
    decisions, _ = map_screen(fs, PROF)
    got = {d.ref: d.value for d in decisions}
    assert got["#p"] == "OYO" and got["#c"] == "Tata AIG" and got["#y"] == "Tata AIG"
