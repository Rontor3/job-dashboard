import json
from datetime import datetime, timezone

from job_dashboard.sources.cdp import indeed

MS = 1_790_000_000_000


def C(key, title="Data Scientist", company="Acme", **kw):
    d = dict(jobkey=key, title=title, company=company, formattedLocation="Bengaluru, Karnataka", pubDate=MS,
             formattedRelativeTime="Just posted", sponsored=False, snippet="s", indeedApplyable=False, link="/x")
    d.update(kw)
    return {k: v for k, v in d.items() if v is not None}


def search_html(cards):
    model = {"metaData": {"mosaicProviderJobCardsModel": {"results": cards}}}
    return ("<html><head></head><body><script>\nwindow.mosaic.providerData[\"mosaic-provider-jobcards\"]="
            + json.dumps(model) + ";\nwindow.other = 1;\n</script></body></html>")


def detail_html(**kw):
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Data Scientist",
          "description": "<p>Build models</p><ul><li>Python</li></ul>", "datePosted": "2026-09-20",
          "directApply": False, "hiringOrganization": {"name": "Acme"}}
    ld.update(kw)
    return ('<html><script type="application/ld+json">{"@type":"BreadcrumbList"}</script>'
            f'<script type="application/ld+json">{json.dumps(ld)}</script></html>')


def test_constants():
    assert indeed.SITE == "indeed" and indeed.LOCATIONS == ("India", "Remote")
    assert "machine learning engineer" in indeed.TERMS and len(indeed.TERMS) == 5


def test_search_url_is_date_sorted_and_pages_by_ten():
    assert indeed.search_url("machine learning engineer", "India", 0) == \
        "https://in.indeed.com/jobs?q=machine+learning+engineer&l=India&sort=date&start=0"
    assert indeed.search_url("ai engineer", "Remote", 2).endswith("&l=Remote&sort=date&start=20")


def test_parse_search_maps_cards_and_drops_incomplete_ones():
    html = search_html([C("k1", indeedApplyable=True), C("k2", sponsored=True), C(None), C("k4", title=None), C("k5", company=None)])
    assert indeed.parse_search(html) == [
        dict(id="k1", title="Data Scientist", company="Acme", location="Bengaluru, Karnataka", pub_ms=MS, sponsored=False, native=True),
        dict(id="k2", title="Data Scientist", company="Acme", location="Bengaluru, Karnataka", pub_ms=MS, sponsored=True, native=False)]


def test_parse_search_missing_or_malformed_json_is_empty():
    assert indeed.parse_search("<html>nothing</html>") == []
    assert indeed.parse_search('window.mosaic.providerData["mosaic-provider-jobcards"]={not json};\n') == []
    assert indeed.parse_search(search_html([]).replace("mosaicProviderJobCardsModel", "other")) == []


def test_parse_detail_reads_jobposting_ld_json():
    d = indeed.parse_detail(detail_html(directApply=True))
    assert d == {"description": "Build models\nPython", "posted": "2026-09-20", "direct": True}


def test_parse_detail_none_without_jobposting_or_description():
    assert indeed.parse_detail("<html>no ld</html>") is None
    assert indeed.parse_detail(detail_html(description="")) is None
    assert indeed.parse_detail('<script type="application/ld+json">{oops</script>') is None


def test_is_challenge_markers():
    assert indeed.is_challenge("<html><title>Just a moment...</title></html>")
    assert indeed.is_challenge('<script src="/cdn-cgi/challenge-platform/x.js"></script>')
    assert indeed.is_challenge('<div class="cf-turnstile"></div>')
    assert not indeed.is_challenge(search_html([C("k1")]))
    assert not indeed.is_challenge("<html>plain empty results</html>")


def test_to_listing_native_from_card_or_detail_else_external():
    card = indeed.parse_search(search_html([C("k1")]))[0]
    j = indeed.to_listing(card, {"description": "d", "posted": "2026-09-20", "direct": False})
    assert (j.source, j.external_id, j.title, j.company, j.location, j.description) == \
        ("indeed", "k1", "Data Scientist", "Acme", "Bengaluru, Karnataka", "d")
    assert j.job_url == "https://in.indeed.com/viewjob?jk=k1" and j.apply_url is None and j.apply_kind == "external"
    assert j.posted_date == datetime.fromtimestamp(MS / 1000, timezone.utc).isoformat()
    assert indeed.to_listing({**card, "native": True}, {"description": "d", "posted": None, "direct": False}).apply_kind == "native"
    assert indeed.to_listing(card, {"description": "d", "posted": None, "direct": True}).apply_kind == "native"


def test_to_listing_posted_falls_back_to_dateposted():
    card = {**indeed.parse_search(search_html([C("k1")]))[0], "pub_ms": None}
    assert indeed.to_listing(card, {"description": "d", "posted": "2026-09-20", "direct": False}).posted_date == "2026-09-20"
    assert indeed.to_listing(card, {"description": "d", "posted": None, "direct": False}).posted_date is None
