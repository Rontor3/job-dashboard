"""Runs each enabled, due browser adapter in isolation and records its state."""
from __future__ import annotations

from job_dashboard.sources.cdp import linkedin, state
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext, Blocked, SiteResult

ADAPTERS = {linkedin.SITE: (linkedin.run, linkedin.TERMS)}
CDP_URL = "http://localhost:9222"
# mode -> (max search pages per term, page-load cap, stop after N consecutive known)
LIMITS = {"incremental": (3, 30, 10), "backfill": (2, 60, 10**9)}


def fetch_browser_sources(conn, *, adapters=ADAPTERS, cdp_url=CDP_URL, session_factory=None,
                          reachable=cdp_reachable, now=None):
    listings, results = [], []
    for site, (run, terms) in adapters.items():
        if not state.enabled(conn, site):
            continue
        if not state.due(conn, site, now=now):
            results.append(SiteResult(site, note="not due"))
            continue
        if not reachable(cdp_url):
            results.append(SiteResult(site, note="Chrome CDP not reachable"))
            continue
        mode = state.mode_for(conn, site)
        pages, cap, stop_known = LIMITS[mode]
        known = _known_fn(conn, site)
        ctx = AdapterContext(mode=mode, known=known, terms=terms, max_pages=pages, stop_after_known=stop_known)
        res = SiteResult(site, mode=mode)
        try:
            factory = session_factory or (lambda c: CdpSession(cdp_url, max_loads=c))
            with factory(cap) as session:
                found = run(session, ctx)
            res.new, res.skipped_known, res.pages = len(found), ctx.stats["skipped_known"], ctx.stats["pages"]
            listings.extend(found)
            state.record_run(conn, site, ok=True, new=res.new, skipped=res.skipped_known,
                             backfill_done=True, now=now)
        except Blocked as exc:
            res.note = f"blocked: {exc}"
            state.record_run(conn, site, ok=False, error=f"Blocked: {exc}", now=now)
        except Exception as exc:                       # one site must never break Refresh
            res.note = f"error: {exc}"
            state.record_run(conn, site, ok=False, error=f"{type(exc).__name__}: {exc}", now=now)
        results.append(res)
    return listings, results


def _known_fn(conn, site):
    def known(external_id, url):
        return conn.execute(
            "SELECT 1 FROM jobs WHERE (source=? AND external_id=?) OR job_url=? LIMIT 1",
            (site, external_id, url)).fetchone() is not None
    return known
