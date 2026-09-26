"""Runs each enabled, due browser adapter in isolation and records its state."""
from __future__ import annotations

from datetime import datetime, timezone

from job_dashboard.sources.cdp import linkedin, naukri, state
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext, Blocked, SiteResult, norm_text

ADAPTERS = {linkedin.SITE: (linkedin.run, linkedin.TERMS), naukri.SITE: (naukri.run, naukri.TERMS)}
CDP_URL = "http://localhost:9222"
# mode -> (max search pages per term, page-load cap, stop after N consecutive known)
LIMITS = {"incremental": (3, 30, 10), "backfill": (2, 60, 10**9)}
WINDOWS = {"linkedin": tuple(sorted(linkedin.TPR)), "naukri": tuple(sorted(naukri.AGES))}      # site -> look-back buckets (hours)
LIMITS_BY_SITE = {"naukri": {"incremental": (5, 40, 10**9), "backfill": (5, 80, 10**9)}}        # site -> {mode: (max_pages, load_cap, stop_after_known)}; missing -> LIMITS


def fetch_browser_sources(conn, *, adapters=ADAPTERS, cdp_url=CDP_URL, session_factory=None,
                          reachable=cdp_reachable, now=None):
    listings, results = [], []
    for site, (run, terms) in adapters.items():
        if not state.enabled(conn, site):
            continue
        if not state.due(conn, site, now=now):
            err = (state.get(conn, site) or {}).get("last_error")
            results.append(SiteResult(site, note=f"not due (last error: {err})" if err else "not due"))
            continue
        if not reachable(cdp_url):
            results.append(SiteResult(site, note="Chrome CDP not reachable"))
            continue
        mode = state.mode_for(conn, site)
        pages, cap, stop_known = LIMITS_BY_SITE.get(site, LIMITS)[mode]
        known, redate = _known_fn(conn, site), _redate_fn(conn, site)
        ctx = AdapterContext(mode=mode, known=known, redate=redate, terms=terms, max_pages=pages, stop_after_known=stop_known,
                             known_text=_known_text_fn(conn, site),
                             hours=_window(mode, state.get(conn, site), now, WINDOWS.get(site, WINDOWS["linkedin"])))
        res = SiteResult(site, mode=mode)
        try:
            factory = session_factory or (lambda c: CdpSession(cdp_url, max_loads=c))
            with factory(cap) as session:
                try:
                    found = run(session, ctx)
                finally:
                    res.pages = getattr(session, "loads", 0)
            capped = bool(ctx.stats.get("capped"))
            res.new, res.skipped_known = len(found), ctx.stats["skipped_known"]
            res.redated = ctx.stats.get("redated", 0)
            if capped:
                res.note = "cap reached (resumes next run)"
            done = (not capped and bool(found or ctx.stats["pages"])) if mode == "backfill" else None
            listings.extend(found)
            state.record_run(conn, site, ok=True, new=res.new, skipped=res.skipped_known,
                             backfill_done=done, now=now)
        except Blocked as exc:
            res.note = f"blocked: {exc}"
            state.record_run(conn, site, ok=False, error=f"Blocked: {exc}", now=now)
        except Exception as exc:                       # one site must never break Refresh
            res.note = f"error: {exc}"
            state.record_run(conn, site, ok=False, error=f"{type(exc).__name__}: {exc}", now=now)
        results.append(res)
    return listings, results


def _window(mode, row, now, windows):
    """Incremental look-back: at least the smallest bucket >= 48h, widened to cover the gap since the last success."""
    if mode == "backfill":
        return max(windows)
    floor = next((b for b in windows if b >= 48), max(windows))
    last = (row or {}).get("last_success_at")
    if not last:
        return floor
    h = max(48, ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(last)).total_seconds() / 3600)
    return next((b for b in windows if b >= h), max(windows))


def _known_text_fn(conn, site):
    def known_text(title, company, location):
        want = (norm_text(title), norm_text(company), norm_text(location))
        return any((norm_text(t), norm_text(c), norm_text(l)) == want for t, c, l in conn.execute(
            "SELECT title, company, location FROM jobs WHERE source=? AND LOWER(company)=LOWER(?)", (site, company or "")))
    return known_text


def _known_fn(conn, site):
    def known(external_id, url):
        return conn.execute(
            "SELECT 1 FROM jobs WHERE (source=? AND external_id=?) OR job_url=? LIMIT 1",
            (site, external_id, url)).fetchone() is not None
    return known


def _redate_fn(conn, site):
    def redate(external_id, url, iso):
        """Only ever moves posted_date forward (reposts); returns True if a row changed."""
        cur = conn.execute(
            "UPDATE jobs SET posted_date=? WHERE ((source=? AND external_id=?) OR job_url=?) "
            "AND (posted_date IS NULL OR posted_date < ?)", (iso, site, external_id, url, iso))
        conn.commit()
        return cur.rowcount > 0
    return redate
