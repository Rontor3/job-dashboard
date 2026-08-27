from career_agent.memory.candidate_profile import CandidateProfile, Experience, Education
from career_agent.orchestrator.profile_resolver import resolve

P = CandidateProfile(
    contact={"full_name": "Rakshit", "email": "r@x.com"},
    experiences=[Experience("Tata AIG", "Data Scientist", "July 2023", "Present", ["b"]),
                 Experience("OYO", "Intern", "May 2022", "Jul 2022", [])],
    education=[Education("IIT", "B.Tech", "CS", "2018", "2022")],
    skills=["Python", "SQL"])

def test_scalar_and_indexed_resolution():
    assert resolve("full_name", P) == "Rakshit"
    assert resolve("employer", P, 0) == "Tata AIG"
    assert resolve("job_title", P, 0) == "Data Scientist"
    assert resolve("employer", P, 1) == "OYO"
    assert resolve("school", P, 0) == "IIT"
    assert resolve("degree", P, 0) == "B.Tech"
    assert resolve("skills", P) == "Python, SQL"

def test_missing_returns_none():
    assert resolve("employer", P, 5) is None
    assert resolve("gpa", P, 0) is None
