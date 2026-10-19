"""Degree levels from the profile (highest + per education row, K-12 rows) and the Roles & Responsibilities ask."""
from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Education, Experience
from career_agent.orchestrator.judgment import JudgmentContext, judge, role_description_question
from career_agent.orchestrator.profile_resolver import degree_level, highest_degree_level, row_degree_level
from career_agent.orchestrator.screen_review import map_screen

LEVELS = ["High School Graduate or Equivalent", "Associate's Degree", "Bachelor's Degree", "Master's Degree",
          "Doctorate", "Post-Doctorate", "Technical/Trade School", "Other"]
IIT = Education("IIT (BHU) Varanasi", "B.Tech", "Ceramic Engineering")
P = CandidateProfile(contact={"full_name": "Rakshit"}, education=[IIT],
                     experiences=[Experience("Tata AIG", "Data Scientist", "2023", "Present", ["Built models"])])


def test_degree_level_mapping():
    assert degree_level("B.Tech") == "Bachelor's Degree"
    assert degree_level("M.Tech") == "Master's Degree"
    assert degree_level("PhD") == "Doctorate"
    assert degree_level("Diploma in Civil") == "Technical/Trade School"
    assert degree_level("12th (CBSE)") == "High School Graduate or Equivalent"
    assert degree_level("Bachelor of Arts") == "Bachelor's Degree"
    assert degree_level("Philosophy") is None


def test_highest_is_top_level_across_education():
    p = CandidateProfile(education=[Education("City Montessori School", "12th"), IIT,
                                    Education("Some Institute", "M.Tech")])
    assert highest_degree_level(p) == "Master's Degree"
    assert highest_degree_level(CandidateProfile(education=[])) is None


def test_row_degree_follows_its_school():
    assert row_degree_level(P, 0, "IIT BHU Varanasi") == "Bachelor's Degree"
    assert row_degree_level(P, 1, "City Montessori School") == "High School Graduate or Equivalent"
    assert row_degree_level(P, 1, "Unknown Engineering College") is None      # never guessed
    assert row_degree_level(P, 0, "") == "Bachelor's Degree"                  # no school text: by index
    assert row_degree_level(P, 3, "") is None


def _sel(ref, label, purpose, options, row=-1, section="Education", value=""):
    return Field(ref, "select", label, True, options, None, purpose, section=section, row=row, value=value)


OPTS = LEVELS + ["(Brazil) PHD"]


def test_map_screen_highest_and_rows():
    form = [_sel("#hi", "Highest Degree/Diploma Obtained *", "degree", OPTS),
            _sel("#d0", "Degree *", "degree", OPTS, row=0),
            _sel("#d1", "Degree *", "degree", OPTS, row=1),
            Field("#s0", "text", "School *", True, [], None, "school", section="Education", row=0,
                  value="IIT (BHU) Varanasi"),
            Field("#s1", "text", "School *", True, [], None, "school", section="Education", row=1,
                  value="City Montessori School")]
    decisions, needs = map_screen(form, P)
    d = {x.ref: x.value for x in decisions if x.ref.startswith(("#hi", "#d"))}
    assert d == {"#hi": "Bachelor's Degree", "#d0": "Bachelor's Degree", "#d1": "High School Graduate or Equivalent"}
    assert not [f for f in needs if f.purpose == "degree"]


def test_map_screen_unknown_school_row_escalates():
    form = [_sel("#d1", "Degree *", "degree", OPTS, row=1),
            Field("#s1", "text", "School *", True, [], None, "school", section="Education", row=1,
                  value="Unknown Engineering College")]
    decisions, needs = map_screen(form, P)
    assert [f.ref for f in needs] == ["#d1"] and not [x for x in decisions if x.ref == "#d1"]


def test_role_description_box_is_asked_from_its_role():
    box = Field("#r", "textarea", "Roles & Responsibilities", False, [], None, None,
                section="Experience", row=0)
    assert role_description_question(box, ("Tata AIG",)) == (
        "Describe your responsibilities and achievements in this role at Tata AIG")
    assert role_description_question(box, ()) == "Describe your responsibilities and achievements in this role"
    outside = Field("#r2", "textarea", "Roles & Responsibilities", False, [], None, None, section="Skills", row=-1)
    assert role_description_question(outside, ("Tata AIG",)) is None


def test_role_box_reaches_the_writer_with_the_role_question():
    asked = []

    def longform(question, f, job):
        asked.append(question)
        return {"answer": "Built fraud models.", "confidence": 90, "flags": []}

    box = Field("#r", "textarea", "Roles & Responsibilities", True, [], None, None, section="Experience", row=0)
    ctx = JudgmentContext(job={"title": "DS"}, profile_text="x", longform=longform, companies=("Tata AIG",))
    answered, still, _ = judge([box], ctx, llm=lambda p: "")
    assert asked == ["Describe your responsibilities and achievements in this role at Tata AIG"]
    assert [d.value for d in answered] == ["Built fraud models."] and not still
