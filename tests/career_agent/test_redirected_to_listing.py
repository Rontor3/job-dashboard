from career_agent.browser.page_prep import redirected_to_listing as r


def test_posting_that_lands_on_the_job_list_is_gone():
    assert r("https://himalayas.app/companies/experian/jobs/expert-data-scientist", "https://himalayas.app/jobs")
    assert r("https://www.acme.com/careers/job/123", "https://acme.com/")


def test_login_apply_step_or_other_host_is_not_gone():
    assert not r("https://acme.com/careers/job/123", "https://acme.com/login")
    assert not r("https://acme.com/careers/job/123", "https://acme.com/careers/job/123/apply")
    assert not r("https://acme.com/careers/job/123", "https://acme.wd1.myworkdayjobs.com/jobs")
    assert not r("https://acme.com/jobs", "https://acme.com/jobs")
    assert not r("https://acme.com/careers/job/123", "https://acme.com/jobs?q=data")
