import os
import pytest
from job_dashboard.match.relevance import is_target_role
from job_dashboard.sources.cdp import ycstartups
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext

pytestmark = pytest.mark.skipif(os.environ.get("RUN_CDP_TESTS") != "1" or not cdp_reachable("http://localhost:9222"),
                                reason="needs RUN_CDP_TESTS=1 and Chrome on :9222")


def test_ycstartups():
    ctx = AdapterContext("incremental", lambda i, u: False, ["data scientist"], max_pages=1, stop_after_known=10**9, hours=48)
    with CdpSession("http://localhost:9222", max_loads=6) as s:
        jobs = ycstartups.run(s, ctx)
    print(ycstartups.SITE, len(jobs), "jobs; loads", s.loads, "stats", ctx.stats)
    assert jobs and all(j.title and j.company and j.description and j.job_url for j in jobs)
    assert all(is_target_role(j.title) for j in jobs)
    assert all(j.apply_url is None and j.apply_kind == "native" for j in jobs)
