"""FastAPI for the agent service's tests (agent/test/e2e.test.ts): run it with uvicorn and JOB_DASHBOARD_DATA_DIR set
to a temp dir. Fake bag-of-words embeddings (no ONNX download), one seeded job, no model calls."""
import re
import zlib

import numpy as np

from career_agent.memory import qbank
from job_dashboard import paths
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


def _bow(texts):
    out = np.zeros((len(texts), 256), dtype="float32")
    for i, t in enumerate(texts):
        for tok in re.findall(r"[a-z0-9]+", (t or "").lower()):
            out[i, zlib.crc32(tok.encode()) % 256] += 1.0
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(n == 0, 1, n)


qbank.default_embed = _bow
_conn = init_db(str(paths.DB))
if not _conn.execute("SELECT 1 FROM jobs").fetchone():
    insert_job(_conn, JobListing(source="s", title="ML Engineer", company="Acme", job_url="https://x/1", description="jd"))
_conn.close()

from job_dashboard.api.app import create_app  # noqa: E402

app = create_app(db_path=str(paths.DB), qa_embed=_bow)
