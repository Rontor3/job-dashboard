from job_dashboard.sources.cdp import naukri as nk

def D(i, title="Data Scientist", company="Acme", ext=False, **kw):
    d = {"jobId": str(i), "title": title, "companyName": company, "createdDate": 1790000000000,
         "jdURL": f"/job-listings-x-{i}?src=abc", "jobDescription": "<b>Snip</b> pet", "companyApplyJob": ext,
         "applyRedirectUrl": "https://acme.com/apply" if ext else None,
         "placeholders": [{"type": "experience", "label": "3-6 Yrs"}, {"type": "salary", "label": "Not disclosed"},
                          {"type": "location", "label": "Bengaluru"}]}
    d.update(kw); return d

SEARCH = {"noOfJobs": 1967, "jobDetails": [D(1), D(2, ext=True), {"title": "no id"}]}
DETAIL = {"jobDetails": {"jobId": "2", "description": "<p>Build <b>models</b></p><ul><li>Python</li></ul>&amp; more"}}


def test_parse_search():
    cards, total = nk.parse_search(SEARCH)
    assert total == 1967 and [c["id"] for c in cards] == ["1", "2"]
    c = cards[1]
    assert c["external"] is True and c["apply_url"] == "https://acme.com/apply"
    assert c["location"] == "Bengaluru" and c["salary"] is None          # "Not disclosed" dropped
    assert c["jd_url"] == "/job-listings-x-2"                            # query string stripped


def test_parse_detail_and_html_to_text():
    d = nk.parse_detail(DETAIL)
    assert d["job_id"] == "2" and "Build models" in d["description"] and "Python" in d["description"]
    assert "<" not in d["description"] and "& more" in d["description"]
    assert nk.parse_detail({"nope": 1}) is None


def test_to_listing_native_and_external():
    cards, _ = nk.parse_search(SEARCH)
    n, e = nk.to_listing(cards[0], "desc"), nk.to_listing(cards[1], "desc")
    assert (n.source, n.external_id, n.job_url) == ("naukri", "1", "https://www.naukri.com/job-listings-x-1")
    assert (n.apply_kind, n.apply_url) == ("native", None)
    assert (e.apply_kind, e.apply_url) == ("external", "https://acme.com/apply")
    assert n.posted_date.startswith("2026-") and n.location == "Bengaluru"


def test_collapse_key_ignores_case_spacing_and_punctuation():
    a, b, c = (nk.parse_search({"jobDetails": [D(i, title=t, company=co)]})[0][0] for i, t, co in
               [(1, "Data  Scientist!", "Consult Asia"), (2, "data scientist", "CONSULT ASIA"), (3, "Data Scientist", "Other")])
    assert nk.collapse_key(a) == nk.collapse_key(b) != nk.collapse_key(c)


def test_search_url():
    assert nk.search_url("machine learning engineer", 24) == "https://www.naukri.com/machine-learning-engineer-jobs?jobAge=1"
    assert nk.search_url("ai engineer", 720, page=3) == "https://www.naukri.com/ai-engineer-jobs-3?jobAge=30"
