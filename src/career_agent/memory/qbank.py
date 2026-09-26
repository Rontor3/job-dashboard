"""Question bank store — canonical application questions and every confirmed
wording of them. Spec: docs/superpowers/specs/2026-09-26-question-bank-design.md

qbank_entry   one row per distinct question: type, the user's answer (or the
              profile column / rule that produces it), option synonyms, shape.
qbank_wording every wording confirmed to mean an entry, with its MiniLM vector:
              repeat wordings are exact hits, new ones are compared by meaning.

data/qbank_seed.json carries questions/wordings/rules but NEVER answers —
answers are typed on the dashboard and live only in jobs.db (PII stays local)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from job_dashboard.qa_store import norm_key as norm

SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "qbank_seed.json"
_JSON_COLS = ("slots", "synonyms")
_DEF_COLS = ("question", "topic", "atype", "profile_ref", "rule", "slots", "synonyms", "shape")
_KIND_ATYPE = {"select": "choice", "radio_group": "choice", "combobox": "choice", "checkbox": "bool"}


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS qbank_entry (
        id TEXT PRIMARY KEY, question TEXT NOT NULL, topic TEXT, atype TEXT NOT NULL,
        answer TEXT, profile_ref TEXT, rule TEXT, slots TEXT, synonyms TEXT, shape TEXT,
        status TEXT NOT NULL DEFAULT 'active', updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS qbank_wording (
        norm TEXT PRIMARY KEY, entry_id TEXT NOT NULL, vec BLOB NOT NULL,
        source TEXT NOT NULL, text TEXT)""")
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(cur, r) -> dict:
    d = dict(zip([c[0] for c in cur.description], r))
    d["slots"] = json.loads(d["slots"]) if d.get("slots") else []
    d["synonyms"] = json.loads(d["synonyms"]) if d.get("synonyms") else {}
    return d


def get_entry(conn, entry_id):
    cur = conn.execute("SELECT * FROM qbank_entry WHERE id=?", (entry_id,))
    r = cur.fetchone()
    return _row(cur, r) if r else None


def entries(conn, status: str = "active") -> list[dict]:
    cur = conn.execute("SELECT * FROM qbank_entry WHERE status=? ORDER BY topic, id", (status,))
    return [_row(cur, r) for r in cur.fetchall()]


def upsert_entry(conn, e: dict) -> None:
    """Insert or refresh an entry's definition. Never touches `answer` or
    `status`, so re-seeding can't erase what the user typed or retired."""
    vals = [json.dumps(e[k]) if k in _JSON_COLS and e.get(k) is not None else e.get(k)
            for k in _DEF_COLS]
    conn.execute(
        f"INSERT INTO qbank_entry (id, {', '.join(_DEF_COLS)}, updated_at) "
        f"VALUES (?, {', '.join('?' * len(_DEF_COLS))}, ?) ON CONFLICT(id) DO UPDATE SET "
        f"{', '.join(f'{k}=excluded.{k}' for k in _DEF_COLS)}, updated_at=excluded.updated_at",
        [e["id"], *vals, _now()])
    conn.commit()


def set_answer(conn, entry_id, answer) -> bool:
    cur = conn.execute("UPDATE qbank_entry SET answer=?, updated_at=? WHERE id=?",
                       (None if answer is None else str(answer).strip(), _now(), entry_id))
    conn.commit()
    return cur.rowcount > 0


def set_status(conn, entry_id, status: str) -> bool:
    if status not in ("active", "superseded"):
        raise ValueError(status)
    cur = conn.execute("UPDATE qbank_entry SET status=?, updated_at=? WHERE id=?",
                       (status, _now(), entry_id))
    conn.commit()
    return cur.rowcount > 0


def add_wording(conn, text, entry_id, vec, source, *, replace=False) -> bool:
    """Link a wording to an entry. replace=False keeps an existing link (seed and
    migration must not undo a human re-point); replace=True moves it."""
    key = norm(text)
    if not key:
        return False
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    cur = conn.execute(
        f"{verb} INTO qbank_wording (norm, entry_id, vec, source, text) VALUES (?,?,?,?,?)",
        (key, entry_id, np.asarray(vec, dtype="float32").tobytes(), source, text))
    conn.commit()
    return cur.rowcount > 0


def exact(conn, text):
    r = conn.execute(
        "SELECT w.entry_id FROM qbank_wording w JOIN qbank_entry e ON e.id=w.entry_id "
        "WHERE w.norm=? AND e.status='active'", (norm(text),)).fetchone()
    return r[0] if r else None


def wordings(conn) -> list:
    rows = conn.execute(
        "SELECT w.norm, w.entry_id, w.vec FROM qbank_wording w JOIN qbank_entry e "
        "ON e.id=w.entry_id WHERE e.status='active'").fetchall()
    return [(n, e, np.frombuffer(v, dtype="float32")) for n, e, v in rows]


def wordings_for(conn, entry_id) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT COALESCE(text, norm) FROM qbank_wording WHERE entry_id=? ORDER BY source, norm",
        (entry_id,))]


def new_entry_id(conn, question) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", norm(question)).strip("_")[:40] or "question"
    eid, n = base, 2
    while conn.execute("SELECT 1 FROM qbank_entry WHERE id=?", (eid,)).fetchone():
        eid, n = f"{base}_{n}", n + 1
    return eid


def add_entry(conn, *, question, kind, answer, embed, topic="misc") -> str:
    """A human-confirmed new question (dashboard 'save as new entry')."""
    eid = new_entry_id(conn, question)
    upsert_entry(conn, {"id": eid, "question": question, "topic": topic,
                        "atype": _KIND_ATYPE.get(kind, "text")})
    set_answer(conn, eid, answer)
    add_wording(conn, question, eid, embed([question])[0], "human", replace=True)
    return eid


def load_seed(conn, embed, path=SEED_PATH) -> int:
    data = json.loads(Path(path).read_text())
    for e in data["entries"]:
        upsert_entry(conn, e)
        texts = [e["question"], *e.get("wordings", [])]
        for t, v in zip(texts, embed(texts)):
            add_wording(conn, t, e["id"], v, "seed")
    return len(data["entries"])


def seed_if_empty(conn, embed, path=SEED_PATH) -> int:
    ensure(conn)
    if conn.execute("SELECT 1 FROM qbank_entry LIMIT 1").fetchone():
        return 0
    return load_seed(conn, embed, path)


_EF = None


def default_embed(texts):
    """Local MiniLM (Chroma's bundled ONNX model): no network, PII stays on-device."""
    global _EF
    if _EF is None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _EF = DefaultEmbeddingFunction()
    v = np.asarray(_EF(list(texts)), dtype="float32")
    return v / np.linalg.norm(v, axis=1, keepdims=True)
