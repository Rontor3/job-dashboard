from job_dashboard.match.apply_type import classify_apply_type as c


def test_ats_domain_is_easy_fill():
    assert c("jobspy:linkedin", "https://jobs.ashbyhq.com/ello/abc")["fill"] == "easy"
    assert c("jobspy:indeed", "https://boards.greenhouse.io/acme/jobs/1")["kind"] == "external-ats"
    assert c("x", "https://acme.myworkdayjobs.com/careers/job/1")["label"] == "ATS form"


def test_source_defaults():
    assert c("himalayas", "https://himalayas.app/x")["fill"] == "easy"          # links out
    assert c("himalayas", "https://himalayas.app/x")["kind"] == "company-site"
    assert c("jobspy:linkedin", "https://www.linkedin.com/jobs/view/1")["kind"] == "linkedin"
    assert c("jobspy:indeed", "https://indeed.com/viewjob?jk=1")["kind"] == "indeed"
    assert c("wellfound", "https://wellfound.com/jobs/1")["kind"] == "wellfound"
    assert c("mystery", "https://example.org/job/1")["fill"] == "manual"


def test_never_raises_on_junk():
    assert c(None, None)["kind"] == "other"
    assert c("", "")["fill"] == "manual"


def test_board_urls_go_to_the_board_agent():
    cases = {"https://www.naukri.com/job-listings-x": ("naukri", "Naukri"),
             "https://www.linkedin.com/jobs/view/1": ("linkedin", "LinkedIn Easy Apply"),
             "https://in.indeed.com/viewjob?jk=1": ("indeed", "Indeed SmartApply"),
             "https://www.iimjobs.com/j/x": ("iimjobs", "iimjobs"),
             "https://www.instahyre.com/job-1": ("instahyre", "Instahyre"),
             "https://wellfound.com/jobs/1": ("wellfound", "Wellfound"),
             "https://www.workatastartup.com/jobs/1": ("workatastartup", "Work at a Startup (YC)")}
    for url, (kind, label) in cases.items():
        assert c("any", url) == {"kind": kind, "label": label, "fill": "agent"}, url


def test_native_easy_apply_uses_the_linkedin_board():
    r = c("linkedin", "https://www.linkedin.com/jobs/view/1", apply_kind="native")
    assert r["kind"] == "linkedin" and r["fill"] == "agent"


def test_external_uses_apply_url_host():
    r = c("linkedin", "https://www.linkedin.com/jobs/view/1", "external", "https://boards.greenhouse.io/x/1")
    assert r["kind"] == "external-ats" and r["fill"] == "easy"


def test_external_unknown_host_is_company_site_maybe():
    r = c("linkedin", "https://www.linkedin.com/jobs/view/1", "external", "https://acme.com/apply")
    assert r == {"kind": "external", "label": "Company site", "fill": "maybe"}


def test_null_apply_kind_falls_back_to_old_heuristic():
    assert c("linkedin", "https://www.linkedin.com/jobs/view/1")["kind"] == "linkedin"
