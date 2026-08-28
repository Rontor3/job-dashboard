from types import SimpleNamespace

from career_agent.memory.candidate_profile import (
    blocks_to_profile, CandidateProfile, education_from_segments,
)

BLOCKS = [
    {"kind": "experience", "title": "Data Scientist, Tata AIG — July 2023 – Present, Mumbai",
     "bullets": [], "group": "Tata AIG", "roleHeader": True, "excluded": False},
    {"kind": "experience", "title": "Health Fraud Pipeline",
     "bullets": ["Built fraud models, ROC>85."], "group": "Tata AIG",
     "roleHeader": False, "excluded": False},
    {"kind": "experience", "title": "Send Time Optimization",
     "bullets": ["skip me"], "group": "Tata AIG", "roleHeader": False, "excluded": True},
    {"kind": "skills", "title": "Programming",
     "bullets": ["**Programming**: Python, SQL, AWS"], "excluded": False},
]

def test_groups_experience_by_company_and_reads_roleheader():
    p = blocks_to_profile(BLOCKS, contact={"full_name": "Rakshit"})
    assert isinstance(p, CandidateProfile)
    assert p.contact["full_name"] == "Rakshit"
    tata = [e for e in p.experiences if e.company == "Tata AIG"]
    assert len(tata) == 1
    e = tata[0]
    assert e.title == "Data Scientist"
    assert e.start == "July 2023" and e.end == "Present"
    assert "Built fraud models, ROC>85." in e.bullets
    assert all("skip me" not in b for b in e.bullets)   # excluded block dropped

def test_skills_parsed():
    p = blocks_to_profile(BLOCKS, contact={})
    assert "Python" in p.skills and "AWS" in p.skills


def test_education_parsed_from_segments():
    # education lives in the fixed segment library, not the layout blocks
    segs = [SimpleNamespace(kind="skills", title="Programming"),
            SimpleNamespace(kind="education", title="Education: B.Tech, IIT (BHU) Varanasi")]
    edu = education_from_segments(segs)
    assert len(edu) == 1
    assert edu[0].degree == "B.Tech"
    assert edu[0].school == "IIT (BHU) Varanasi"


def test_education_with_dates_populates_start_end():
    segs = [SimpleNamespace(kind="education", title="Education: B.Tech, IIT BHU — 2018 – 2022")]
    e = education_from_segments(segs)[0]
    assert e.degree == "B.Tech" and e.school == "IIT BHU"
    assert e.start == "2018" and e.end == "2022"
