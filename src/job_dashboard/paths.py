"""Every file the app writes lives under ONE data root, so a backup is one folder copy.

Root: ``$JOB_DASHBOARD_DATA_DIR`` (relative paths resolve against the repo), else ``<repo>/data``.
Nothing is written to ``~``, ``/tmp`` or the system temp dir.

    jobs.db, jobs_graph.db     SQLite: jobs, profile, question bank, run log / LangGraph checkpoints
    agent_runs/<job_id>/       per-run logs and screenshots
    answer_style/              essay ingredient bank
    resumes/                   rendered résumés and cover letters
    secrets/                   site credentials, Gmail OAuth, portal session cookies (never committed)
    state/                     portal rate-limit state
    browser/profile/           the agent's own Chrome profile (logins live here, isolated from your Chrome)
    tmp/                       debug screenshots, OTP hand-off file
    cache/                     downloaded model weights (HuggingFace, Chroma ONNX) — re-downloadable, skip in backups
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _from_dotenv(key: str) -> str | None:
    """One key from the repo .env (not the whole file: importing this must not switch on other secrets)."""
    try:
        for line in (REPO_ROOT / ".env").read_text().splitlines():
            k, sep, v = line.strip().removeprefix("export ").partition("=")
            if sep and k.strip() == key:
                return v.strip().strip("'\"")
    except OSError:
        pass
    return None


def _root() -> Path:
    raw = os.getenv("JOB_DASHBOARD_DATA_DIR") or _from_dotenv("JOB_DASHBOARD_DATA_DIR")
    if not raw:
        return REPO_ROOT / "data"
    p = Path(os.path.expanduser(raw))
    return (p if p.is_absolute() else REPO_ROOT / p).resolve()


DATA_DIR = _root()
DB = DATA_DIR / "jobs.db"
GRAPH_DB = DATA_DIR / "jobs_graph.db"
AGENT_RUNS = DATA_DIR / "agent_runs"
ANSWER_STYLE = DATA_DIR / "answer_style"
INGREDIENTS = ANSWER_STYLE / "ingredients.json"
RESUMES = DATA_DIR / "resumes"
CURRENT_RESUME = DATA_DIR / "current_resume.pdf"
SECRETS = DATA_DIR / "secrets"
STATE = DATA_DIR / "state"
BROWSER_PROFILE = DATA_DIR / "browser" / "profile"
TMP = DATA_DIR / "tmp"
CACHE = DATA_DIR / "cache"
CHROMA_ONNX = CACHE / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"

# Model downloads land in the data root too, not ~/.cache (must be set before huggingface_hub is imported).
os.environ.setdefault("HF_HOME", str(CACHE / "huggingface"))


def tmp(name: str) -> str:
    """Path for a scratch file inside the data root (created on demand)."""
    TMP.mkdir(parents=True, exist_ok=True)
    return str(TMP / name)


def secret(name: str) -> Path:
    SECRETS.mkdir(parents=True, exist_ok=True)
    return SECRETS / name
