"""LinkedIn hiring-post storage: table + CRUD.

Split out of ``db.py`` (which is at its 500-line cap) following the same pattern
as ``artifacts_store.py``. ``db.init_db`` calls ``_ensure_hiring_posts_table``
and re-exports the CRUD, so callers still ``from job_dashboard.db import ...``.
Dedup is on the post ``url``; a re-fetched post keeps its ``dismissed`` flag.
"""
from datetime import datetime, timezone, timedelta


def _ensure_hiring_posts_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hiring_posts (
               id               INTEGER PRIMARY KEY AUTOINCREMENT,
               url              TEXT UNIQUE NOT NULL,
               poster_name      TEXT,
               poster_headline  TEXT,
               text             TEXT,
               posted_at        TEXT,
               keyword          TEXT,
               fit_score        REAL NOT NULL DEFAULT 0,
               fetched_at       TEXT NOT NULL,
               dismissed        INTEGER NOT NULL DEFAULT 0
           )"""
    )


_HIRING_COLS = ("id", "url", "poster_name", "poster_headline", "text",
                "posted_at", "keyword", "fit_score", "fetched_at", "dismissed")


def upsert_hiring_post(conn, post):
    conn.execute(
        """INSERT INTO hiring_posts
               (url, poster_name, poster_headline, text, posted_at,
                keyword, fit_score, fetched_at)
           VALUES (:url, :poster_name, :poster_headline, :text, :posted_at,
                   :keyword, :fit_score, :fetched_at)
           ON CONFLICT(url) DO UPDATE SET
               text=excluded.text, fit_score=excluded.fit_score,
               fetched_at=excluded.fetched_at, keyword=excluded.keyword""",
        post,
    )
    conn.commit()


def hiring_posts(conn, within_hours=24):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    rows = conn.execute(
        f"""SELECT {', '.join(_HIRING_COLS)} FROM hiring_posts
            WHERE dismissed = 0 AND fetched_at >= ?
            ORDER BY fit_score DESC, id DESC""",
        (cutoff,),
    ).fetchall()
    return [dict(zip(_HIRING_COLS, r)) for r in rows]


def dismiss_hiring_post(conn, post_id):
    conn.execute("UPDATE hiring_posts SET dismissed = 1 WHERE id = ?", (post_id,))
    conn.commit()
