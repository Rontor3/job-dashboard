from job_dashboard.sources.cdp import linkedin as li

CARDS = {"data": {"paging": {"total": 1093}}, "included": [
    {"$type": "com.linkedin.voyager.dash.jobs.JobPostingCard", "jobPostingUrn": "urn:li:fsd_jobPosting:111",
     "jobPostingTitle": "ML Engineer", "primaryDescription": {"text": "Acme"},
     "secondaryDescription": {"text": "Bengaluru, India"}, "tertiaryDescription": {"text": "₹20L"},
     "footerItems": [{"type": "LISTED_DATE", "timeAt": 1790000000000}, {"type": "EASY_APPLY_TEXT"}]},
    {"$type": "com.linkedin.voyager.dash.jobs.JobPostingCard", "jobPostingUrn": "urn:li:fsd_jobPosting:222",
     "jobPostingTitle": "Data Scientist", "primaryDescription": {"text": "Beta"},
     "secondaryDescription": {"text": "Remote"}, "footerItems": [{"type": "LISTED_DATE", "timeAt": 1790000005000}]},
    {"$type": "com.linkedin.voyager.dash.jobs.JobPostingCard", "jobPostingUrn": "urn:li:fsd_jobPosting:333"},  # no title
    {"$type": "com.linkedin.voyager.dash.jobs.JobPosting", "entityUrn": "urn:li:fsd_jobPosting:222", "repostedJob": True},
]}
DETAILS = {"included": [
    {"$type": "x.JobDescription", "entityUrn": "urn:li:fsd_jobPosting:111", "descriptionText": {"text": "Build models"},
     "postedOnText": "2 days ago"},
    {"$type": "x.JobSeekerApplicationDetail", "entityUrn": "urn:li:fsd_jobPosting:111", "onsiteApply": True},
    {"$type": "x.JobDescription", "entityUrn": "urn:li:fsd_jobPosting:222", "descriptionText": {"text": "Analyse"}},
    {"$type": "x.JobSeekerApplicationDetail", "entityUrn": "urn:li:fsd_jobPosting:222", "onsiteApply": False,
     "applicantTrackingSystemName": "Greenhouse", "companyApplyUrl": "https://boards.greenhouse.io/beta/1"},
]}


def test_parse_cards():
    cards, total = li.parse_cards(CARDS)
    assert total == 1093 and set(cards) == {"111", "222"}
    assert cards["111"]["easy_apply_card"] and cards["111"]["listed_ms"] == 1790000000000
    assert cards["222"]["reposted"] is True and not cards["222"]["easy_apply_card"]


def test_parse_details_and_apply_kind():
    d = li.parse_details(DETAILS)
    assert d["111"]["description"] == "Build models" and d["222"]["apply_url"].startswith("https://boards")
    cards, _ = li.parse_cards(CARDS)
    assert li.apply_kind(cards["111"], d["111"]) == "native"
    assert li.apply_kind(cards["222"], d["222"]) == "external"
    assert li.apply_kind(cards["111"], {}) == "native"          # falls back to card flag


def test_to_listing():
    cards, _ = li.parse_cards(CARDS); d = li.parse_details(DETAILS)
    j = li.to_listing(cards["222"], d["222"])
    assert (j.source, j.external_id, j.job_url) == ("linkedin", "222", "https://www.linkedin.com/jobs/view/222")
    assert j.apply_kind == "external" and j.apply_url.startswith("https://boards") and j.description == "Analyse"
    assert j.posted_date.startswith("2026-")


def test_search_url_window_and_paging():
    u = li.search_url("data scientist", 48, start=25)
    assert "keywords=data%20scientist" in u and "f_TPR=r172800" in u and "sortBy=DD" in u and "start=25" in u
    assert "start=" not in li.search_url("x", 24)


def test_search_url_carries_the_geo_id_the_new_search_page_needs():
    assert "geoId=102713980" in li.search_url("ml", 48)


def test_dom_cards_from_the_server_rendered_search_page():
    rows = [["4477884895", ["Selected, Applied Scientist II (Verified job)", "Applied Scientist II", "Amazon", "Bengaluru",
                            "39 connections work here", "Viewed", "·", "Posted 1 day ago"]],
            ["4477800996", ["Machine Learning Engineer", "Cerebras", "Bengaluru (Hybrid)", "·", "Easy Apply"]],
            ["bad", ["x", "y", "z"]]]
    cards = li.dom_cards(rows)
    assert set(cards) == {"4477884895", "4477800996"}
    a, b = cards["4477884895"], cards["4477800996"]
    assert (a["title"], a["company"], a["location"], a["easy_apply_card"]) == ("Applied Scientist II", "Amazon", "Bengaluru", False)
    assert (b["title"], b["company"], b["easy_apply_card"]) == ("Machine Learning Engineer", "Cerebras", True)
    assert li.dom_cards("") == {}


def test_dom_detail_reads_about_the_job_and_the_apply_target():
    view = {"text": "Cerebras\nApply\nAbout the job\n\nBuild models.\nShip them.\n\nAbout the company\nWe make chips.",
            "apply": [["Apply", "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fjobs.ashbyhq.com%2Fc%2F1&trk=x"]]}
    d = li.dom_detail(view)
    assert d["description"] == "Build models.\nShip them."
    assert d["onsite_apply"] is False and d["apply_url"] == "https://jobs.ashbyhq.com/c/1"
    assert li.dom_detail({"text": "About the job\nDo ML.", "apply": [["Easy Apply", ""]]})["onsite_apply"] is True
