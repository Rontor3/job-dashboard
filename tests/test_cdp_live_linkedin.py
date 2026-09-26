import os
import pytest
from job_dashboard.sources.cdp import linkedin as li
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext

pytestmark = pytest.mark.skipif(os.environ.get("RUN_CDP_TESTS") != "1" or not cdp_reachable("http://localhost:9222"),
                                reason="needs RUN_CDP_TESTS=1 and Chrome on :9222")


def test_one_search_page_parses_and_view_page_fires_detail():
    ctx = AdapterContext("incremental", lambda i, u: False, ["machine learning engineer"], max_pages=1, stop_after_known=10)
    with CdpSession("http://localhost:9222", max_loads=6) as s:
        jobs = li.run(s, ctx)
    assert jobs and all(j.title and j.description and j.job_url.startswith("https://www.linkedin.com/jobs/view/") for j in jobs)
    assert {j.apply_kind for j in jobs} <= {"native", "external"}
    print(len(jobs), "jobs;", sum(bool(j.apply_url) for j in jobs), "with apply_url; loads:", s.loads)
