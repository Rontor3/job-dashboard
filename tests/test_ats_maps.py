import pytest
from job_dashboard.apply.ats_maps import load_ats_map, detect_ats, KNOWN_ATS

REQUIRED = {"full_name", "email", "phone", "resume", "cover_letter"}


@pytest.mark.parametrize("name", ["greenhouse", "lever", "ashby", "workday", "wellfound", "generic"])
def test_each_map_loads_and_has_required_intents(name):
    m = load_ats_map(name)
    assert REQUIRED.issubset(m.keys())
    assert all(isinstance(v, list) and v for v in m.values())


def test_detect_ats_from_urls():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/xyz") == "ashby"
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/en-US/x") == "workday"
    assert detect_ats("https://wellfound.com/jobs/12345-ml-engineer") == "wellfound"
    assert detect_ats("https://angel.co/company/acme/jobs/678") == "wellfound"
    assert detect_ats("https://careers.acme.com/apply") == "generic"


def test_load_unknown_raises():
    with pytest.raises((KeyError, FileNotFoundError)):
        load_ats_map("nosuch")
