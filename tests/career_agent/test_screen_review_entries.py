"""Marketing yes/no -> No; Employment 'Current?' and Education 'In Progress' answered from the row's own entry."""
from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Education, Experience
from career_agent.orchestrator.screen_review import map_screen

PROFILE = CandidateProfile(
    contact={},
    experiences=[Experience(company="Tata AIG", title="Data Scientist", start="July 2023", end="Present"),
                 Experience(company="OYO", title="Intern", start="May 2022", end="Jul 2022")],
    education=[Education(school="IIT (BHU)", degree="B.Tech", end="May 2023")],
)


def _radio(ref, label, section="", row=-1, required=True):
    return Field(ref=ref, kind="radio_group", label=label, required=required, options=["Yes", "No"],
                 section=section, row=row)


def _answers(form):
    decisions, needs_human = map_screen(form, PROFILE)
    return {d.ref: d.value for d in decisions}, [f.ref for f in needs_human], {d.ref: d.source for d in decisions}


def test_marketing_yes_no_gets_no_even_when_required():
    form = [_radio("g:sms", "Would you like to receive SMS messages from Koch regarding your application and "
                            "other career opportunities? *"),
            _radio("g:mail", "Select 'Yes' to receive emails about future career opportunities and company news "
                             "from Koch and its affiliate companies. *")]
    values, escalated, sources = _answers(form)
    assert values == {"g:sms": "No", "g:mail": "No"}
    assert escalated == []
    assert set(sources.values()) == {"policy"}


def test_employment_current_follows_the_row_entry():
    form = [_radio("g:cur0", "Current?", section="Employment History", row=0),
            _radio("g:cur1", "Current?", section="Employment History", row=1)]
    values, _, _ = _answers(form)
    assert values == {"g:cur0": "Yes", "g:cur1": "No"}


def test_education_in_progress_is_no_for_a_finished_degree_and_yes_for_an_open_one():
    form = [_radio("g:ip0", "In Progress *", section="Education", row=0)]
    assert _answers(form)[0] == {"g:ip0": "No"}
    open_profile = CandidateProfile(education=[Education(school="X", end="Present")])
    decisions, _ = map_screen([_radio("g:ip0", "In Progress *", section="Education", row=0)], open_profile)
    assert [d.value for d in decisions] == ["Yes"]


def test_unknown_row_still_escalates():
    values, escalated, _ = _answers([_radio("g:cur9", "Current?", section="Employment History", row=9)])
    assert values == {} and escalated == ["g:cur9"]
