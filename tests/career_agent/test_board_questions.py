from career_agent.boards.questions import naukri

# Shape copied from a live Naukri apply-workflow response (2026-09-26, Indium).
Q = [
    {"questionId": "51426676", "questionName": "How many years of experience do you have in Machine Learning?",
     "questionType": "Text Box", "isMandatory": True, "prefillData": ["2.6"], "answerOption": {}},
    {"questionId": "51426680", "questionName": "Please select the city you are currently residing or willing to relocate to",
     "questionType": "Check Box", "isMandatory": False, "prefillData": None,
     "answerOption": {"1": "Hyderabad, Telangana", "2": "Bengaluru, Karnataka"}},
]


def test_naukri_questionnaire_to_fields_and_prefill():
    fields, pre = naukri(Q)
    assert [f.ref for f in fields] == ["q:51426676", "q:51426680"]
    ml, city = fields
    assert ml.kind == "text" and ml.required and ml.purpose == "years_experience"
    assert city.kind == "radio_group" and not city.required
    assert city.options == ["Hyderabad, Telangana", "Bengaluru, Karnataka"]
    assert pre == {"q:51426676": "2.6"}


def test_naukri_empty_questionnaire():
    assert naukri(None) == ([], {})
