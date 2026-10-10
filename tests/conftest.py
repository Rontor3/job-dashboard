class FakeResponse:
    def __init__(self, json_data=None, text="", status_code=200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


import os as _os
import tempfile as _tempfile
from pathlib import Path as _Path

# Tests never read or write the real data root (job_dashboard.paths resolves this at import).
_os.environ["JOB_DASHBOARD_DATA_DIR"] = _tempfile.mkdtemp(prefix="jd-test-data-")

_pw = _Path(__file__).resolve().parents[1] / ".playwright-browsers"
if _pw.is_dir():
    _os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_pw))

# ── question bank fixtures (tests/career_agent/test_qbank*.py, tests/test_qa_api.py) ──
import re as _re
import sqlite3 as _sqlite3
import zlib as _zlib

import numpy as _np
import pytest


def _bow_embed(texts):
    """Deterministic bag-of-words embedding (no ONNX): shared words -> similar vectors."""
    out = _np.zeros((len(texts), 256), dtype="float32")
    for i, t in enumerate(texts):
        for tok in _re.findall(r"[a-z0-9]+", (t or "").lower()):
            out[i, _zlib.crc32(tok.encode()) % 256] += 1.0
    n = _np.linalg.norm(out, axis=1, keepdims=True)
    return out / _np.where(n == 0, 1, n)


@pytest.fixture
def fake_embed():
    return _bow_embed


@pytest.fixture(autouse=True)
def _fast_isolated_defaults(monkeypatch):
    """Tests never load the real MiniLM model (~1s per call), never start/kill the developer's Ollama, never launch Chrome."""
    from career_agent.memory import qbank
    from job_dashboard import agent_browser
    from job_dashboard.apply import local_model
    monkeypatch.setattr(qbank, "default_embed", _bow_embed)
    monkeypatch.setattr(agent_browser, "_executable", lambda: None)      # never launch a real Chrome
    monkeypatch.setattr(agent_browser, "reachable", lambda *a, **k: False)   # ...or touch a running one
    monkeypatch.setattr(agent_browser, "ensure_window", lambda url: None)
    monkeypatch.setattr(local_model, "ensure_running", lambda *a, **k: False)
    monkeypatch.setattr(local_model, "stop", lambda *a, **k: None)


QBANK_ENTRIES = [
    {"id": "sponsorship_required", "question": "Will you require visa sponsorship?", "atype": "bool",
     "wordings": ["Do you need visa sponsorship to work here?"], "answer": "Yes",
     "synonyms": {"Yes": ["I will require sponsorship"]}},
    {"id": "work_arrangement", "question": "What is your preferred work arrangement (remote, hybrid or onsite)?",
     "atype": "choice", "rule": "preference", "answer": "Remote > Hybrid > Onsite",
     "wordings": ["Are you comfortable working in an onsite setting?"],
     "synonyms": {"Remote": ["remote", "work from home"], "Hybrid": ["hybrid"], "Onsite": ["onsite", "on-site", "in office"]}},
    {"id": "hispanic_latino", "question": "Are you Hispanic or Latino?", "atype": "bool",
     "wordings": [], "answer": "No"},
    {"id": "race", "question": "Please identify your race", "atype": "choice",
     "wordings": ["Race"], "profile_ref": "ethnicity"},
    {"id": "home_address", "question": "What is your current residential address?", "atype": "text",
     "shape": "address", "wordings": ["Street address"], "answer": "C-12, Sector 5, Noida 201301"},
    {"id": "local_cities", "question": "Which cities can you work from without relocating?",
     "atype": "text", "wordings": [], "answer": "Noida, Delhi"},
    {"id": "work_location", "question": "What is the address from which you plan on working?",
     "atype": "text", "rule": "local_or_escape", "wordings": []},
    {"id": "notice_period", "question": "What is your notice period in days?", "atype": "number",
     "wordings": ["Notice period"], "answer": "30"},
    {"id": "linkedin_url", "question": "LinkedIn profile URL", "atype": "text", "shape": "url",
     "wordings": [], "answer": "linkedin.com/in/x"},
    {"id": "english_proficiency", "question": "How would you rate your English language skills?",
     "atype": "choice", "wordings": []},
]


@pytest.fixture
def qbank_conn(fake_embed):
    """In-memory bank with QBANK_ENTRIES (Task 1 must exist for this to import)."""
    from career_agent.memory import qbank
    c = _sqlite3.connect(":memory:")
    qbank.ensure(c)
    for e in QBANK_ENTRIES:
        qbank.upsert_entry(c, e)
        if e.get("answer"):
            qbank.set_answer(c, e["id"], e["answer"])
        for t in [e["question"], *e.get("wordings", [])]:
            qbank.add_wording(c, t, e["id"], fake_embed([t])[0], "seed")
    return c


@pytest.fixture
def make_field():
    from career_agent.browser.form_model import Field

    def make(label, kind="text", options=(), description="", ref="#x", **kw):
        return Field(ref=ref, kind=kind, label=label, required=False,
                     options=list(options), description=description, **kw)
    return make
