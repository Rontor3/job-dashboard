import json
import pytest
from job_dashboard.linkedin.voyager import (
    VoyagerClient, LinkedInAuthError, LinkedInRateLimit,
)


def seq_fetch(responses):
    def _fetch(url, headers):
        return responses.pop(0)
    return _fetch


PAGE_WITH_ID = (
    '<html>...<script>queryId&quot;:&quot;voyagerSearchDashClusters.'
    'abc123def456&quot;...</script></html>'
)


def test_resolve_query_id_extracts_from_page():
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([(200, PAGE_WITH_ID)]))
    assert c.resolve_search_query_id() == "voyagerSearchDashClusters.abc123def456"


def test_resolve_query_id_auth_error_on_redirect():
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([(302, "")]))
    with pytest.raises(LinkedInAuthError):
        c.resolve_search_query_id()


def test_search_posts_returns_included_objects():
    search_body = json.dumps({"data": {}, "included": [
        {"$type": "com.linkedin.voyager.dash.search.SearchFeedUpdate", "x": 1},
        {"$type": "other", "y": 2},
    ]})
    # first response resolves the queryId, second is the search result
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([
        (200, PAGE_WITH_ID), (200, search_body),
    ]))
    out = c.search_posts("hiring ML engineer")
    assert isinstance(out, list) and len(out) == 2


def test_search_posts_rate_limit():
    c = VoyagerClient("x", "ajax:1", fetch=seq_fetch([(200, PAGE_WITH_ID), (429, "")]))
    with pytest.raises(LinkedInRateLimit):
        c.search_posts("hiring ML engineer")
