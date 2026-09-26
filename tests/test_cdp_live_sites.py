import os
import pytest
from job_dashboard.sources.cdp import iimjobs, instahyre, wellfound
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext

pytestmark = pytest.mark.skipif(os.environ.get("RUN_CDP_TESTS") != "1" or not cdp_reachable("http://localhost:9222"),
                                reason="needs RUN_CDP_TESTS=1 and Chrome on :9222")


def _run(mod, terms, loads, **kw):
    ctx = AdapterContext("incremental", lambda i, u: False, terms, max_pages=kw.pop("max_pages", 1),
                         stop_after_known=10**9, hours=48, **kw)
    with CdpSession("http://localhost:9222", max_loads=loads) as s:
        jobs = mod.run(s, ctx)
    print(mod.SITE, len(jobs), "jobs; loads", s.loads, "stats", ctx.stats)
    return jobs


def _ok(jobs):
    assert jobs and all(j.title and j.company and j.description and j.job_url for j in jobs)


def test_instahyre():
    _ok(_run(instahyre, ["data scientist"], 6))


def test_iimjobs():
    _ok(_run(iimjobs, ["data scientist"], 6, max_pages=1))


def test_wellfound():
    _ok(_run(wellfound, [], 4, max_pages=2))
