"""Per-site fetch bookkeeping: when a site last ran, whether its backfill finished, last error."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_dashboard import qa_store


def ensure(conn) -> None:
    qa_store.ensure(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS fetch_state (
        site TEXT PRIMARY KEY, last_run_at TEXT, last_success_at TEXT,
        backfill_done INTEGER NOT NULL DEFAULT 0, last_new INTEGER, last_skipped INTEGER,
        last_error TEXT, anchor TEXT)""")
    conn.commit()


def enabled(conn, site: str) -> bool:
    return qa_store.get_setting(conn, f"browser_{site}_enabled") == "1"


def interval_hours(conn) -> float:
    try:
        return float(qa_store.get_setting(conn, "browser_min_interval_hours"))
    except (TypeError, ValueError):
        return 48.0


def get(conn, site: str):
    ensure(conn)
    cur = conn.execute("SELECT * FROM fetch_state WHERE site=?", (site,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def due(conn, site: str, now=None) -> bool:
    row = get(conn, site)
    if not row:
        return True
    ref = row["last_run_at"] if row["last_error"] else row["last_success_at"]   # failures cool down too
    if not ref:
        return True
    now = now or datetime.now(timezone.utc)
    return now - datetime.fromisoformat(ref) >= timedelta(hours=interval_hours(conn))


def mode_for(conn, site: str) -> str:
    row = get(conn, site)
    return "incremental" if row and row["backfill_done"] else "backfill"


def record_run(conn, site, *, ok, new=0, skipped=0, error=None, backfill_done=None, anchor=None, now=None):
    ensure(conn)
    now = (now or datetime.now(timezone.utc)).isoformat()
    prev = get(conn, site) or {}
    conn.execute(
        """INSERT INTO fetch_state (site, last_run_at, last_success_at, backfill_done,
                                    last_new, last_skipped, last_error, anchor)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(site) DO UPDATE SET last_run_at=excluded.last_run_at,
             last_success_at=excluded.last_success_at, backfill_done=excluded.backfill_done,
             last_new=excluded.last_new, last_skipped=excluded.last_skipped, last_error=excluded.last_error,
             anchor=COALESCE(excluded.anchor, fetch_state.anchor)""",
        (site, now, now if ok else prev.get("last_success_at"),
         int(bool(backfill_done)) if backfill_done is not None else int(prev.get("backfill_done") or 0),
         new, skipped, error, str(anchor) if anchor is not None else None))
    conn.commit()


def get_anchor(conn, site: str) -> int:
    row = get(conn, site)
    try:
        return int(row["anchor"]) if row and row["anchor"] else 0
    except (TypeError, ValueError):
        return 0


def record_run_anchor(conn, site: str, anchor: int) -> None:
    ensure(conn)
    conn.execute("INSERT OR IGNORE INTO fetch_state (site) VALUES (?)", (site,))
    conn.execute("UPDATE fetch_state SET anchor=? WHERE site=?", (str(anchor), site))
    conn.commit()
