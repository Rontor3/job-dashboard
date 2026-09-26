import os
import pytest
from job_dashboard.sources.cdp import naukri as nk
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext

pytestmark = pytest.mark.skipif(os.environ.get("RUN_CDP_TESTS") != "1" or not cdp_reachable("http://localhost:9222"),
                                reason="needs RUN_CDP_TESTS=1 and Chrome on :9222")


def test_one_term_two_pages_with_details():
    ctx = AdapterContext("incremental", lambda i, u: False, ["data scientist"], max_pages=2, stop_after_known=10**9, hours=24,
                         known_text=lambda t, c, l: False)
    with CdpSession("http://localhost:9222", max_loads=6) as s:
        jobs = nk.run(s, ctx)
    print(len(jobs), "jobs; collapsed", ctx.stats["collapsed"], "; loads", s.loads)
    assert jobs and all(j.title and j.company and len(j.description) > 200 and j.job_url.startswith("https://www.naukri.com/") for j in jobs)
    assert {j.apply_kind for j in jobs} <= {"native", "external", "unknown"}
    assert len({(j.title.lower(), j.company.lower(), (j.location or "").lower()) for j in jobs}) == len(jobs)
