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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(hiring_posts)")}
    for col in ("fit_reason", "role_title", "company"):
        if col not in cols:
            conn.execute(f"ALTER TABLE hiring_posts ADD COLUMN {col} TEXT")


_HIRING_COLS = ("id", "url", "poster_name", "poster_headline", "text",
                "posted_at", "keyword", "fit_score", "fetched_at", "dismissed", "fit_reason",
                "role_title", "company")


def upsert_hiring_post(conn, post):
    post = {"fit_reason": "", "role_title": "", "company": "", **post}
    conn.execute(
        """INSERT INTO hiring_posts
               (url, poster_name, poster_headline, text, posted_at,
                keyword, fit_score, fetched_at, fit_reason, role_title, company)
           VALUES (:url, :poster_name, :poster_headline, :text, :posted_at,
                   :keyword, :fit_score, :fetched_at, :fit_reason, :role_title, :company)
           ON CONFLICT(url) DO UPDATE SET
               text=excluded.text, fit_score=excluded.fit_score, fit_reason=excluded.fit_reason,
               role_title=excluded.role_title, company=excluded.company,
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
    from job_dashboard.linkedin.contacts import extract_contacts, text_key
    out, seen = [], set()
    for r in rows:
        post = dict(zip(_HIRING_COLS, r))
        key = text_key(post["text"])
        if key in seen:  # same post reshared / fetched under another url
            continue
        seen.add(key)
        post["contacts"] = extract_contacts(post["text"], post["url"])
        # Card state: researched (job row) → Draft email; CV made → link to it.
        job = conn.execute("SELECT id, apply_url, apply_kind FROM jobs WHERE job_url = ?",
                           (post["url"],)).fetchone()
        post["job_id"], post["apply_url"], post["apply_kind"] = job or (None, None, None)
        cv = job and conn.execute("SELECT id FROM resumes WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                                  (job[0],)).fetchone()
        post["resume_id"] = cv[0] if cv else None
        out.append(post)
    return out


def hiring_post(conn, post_id):
    row = conn.execute(
        f"SELECT {', '.join(_HIRING_COLS)} FROM hiring_posts WHERE id = ?", (post_id,)
    ).fetchone()
    return dict(zip(_HIRING_COLS, row)) if row else None


def dismiss_hiring_post(conn, post_id):
    conn.execute("UPDATE hiring_posts SET dismissed = 1 WHERE id = ?", (post_id,))
    conn.commit()
