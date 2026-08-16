from job_dashboard.match.apply_type import classify_apply_type as c


def test_ats_domain_is_easy_fill():
    assert c("jobspy:linkedin", "https://jobs.ashbyhq.com/ello/abc")["fill"] == "easy"
    assert c("jobspy:indeed", "https://boards.greenhouse.io/acme/jobs/1")["kind"] == "external-ats"
    assert c("x", "https://acme.myworkdayjobs.com/careers/job/1")["label"] == "ATS form"


def test_source_defaults():
    assert c("himalayas", "https://himalayas.app/x")["fill"] == "easy"          # links out
    assert c("himalayas", "https://himalayas.app/x")["kind"] == "company-site"
    assert c("jobspy:linkedin", "https://www.linkedin.com/jobs/view/1")["kind"] == "linkedin"
    assert c("jobspy:linkedin", "https://www.linkedin.com/jobs/view/1")["fill"] == "maybe"
    assert c("naukri", "https://www.naukri.com/job-x")["fill"] == "manual"
    assert c("jobspy:indeed", "https://indeed.com/viewjob?jk=1")["kind"] == "indeed"
    assert c("wellfound", "https://wellfound.com/jobs/1")["kind"] == "wellfound"


def test_never_raises_on_junk():
    assert c(None, None)["kind"] == "other"
    assert c("", "")["fill"] == "manual"
