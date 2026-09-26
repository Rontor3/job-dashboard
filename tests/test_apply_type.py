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


def test_native_easy_apply_is_manual():
    r = c("linkedin", "https://www.linkedin.com/jobs/view/1", apply_kind="native")
    assert r["kind"] == "easy-apply" and r["fill"] == "manual"


def test_external_uses_apply_url_host():
    r = c("linkedin", "https://www.linkedin.com/jobs/view/1", "external", "https://boards.greenhouse.io/x/1")
    assert r["kind"] == "external-ats" and r["fill"] == "easy"


def test_external_unknown_host_is_company_site_maybe():
    r = c("linkedin", "https://www.linkedin.com/jobs/view/1", "external", "https://acme.com/apply")
    assert r == {"kind": "external", "label": "Company site", "fill": "maybe"}


def test_null_apply_kind_falls_back_to_old_heuristic():
    assert c("linkedin", "https://www.linkedin.com/jobs/view/1")["kind"] == "linkedin"
