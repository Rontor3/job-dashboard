"""FastAPI for the agent service's tests (agent/test/e2e.test.ts): run it with uvicorn and JOB_DASHBOARD_DATA_DIR set
to a temp dir. Fake bag-of-words embeddings (no ONNX download), one seeded job, no model calls. AGENT_EVAL_SEED=1 also
seeds a blocking question and a guess for the live eval."""
import os
import re
import zlib

import numpy as np

from career_agent.memory import qbank
from job_dashboard import paths, qa_store
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
if os.getenv("AGENT_EVAL_SEED"):
    qa_store.ensure(_conn)
if os.getenv("AGENT_EVAL_SEED") and not _conn.execute("SELECT 1 FROM application_qa").fetchone():
    # The live eval (agent/eval/run.ts): one question blocking the Acme application, one guess to confirm.
    qa_store.record(_conn, job_id=1, run_key="eval", ref="#notice", label="What is your notice period?", kind="text",
                    status="needs_answer")
    qa_store.record(_conn, job_id=1, run_key="eval", ref="#py", label="Years of Python experience?", kind="text",
                    status="filled", answer="5", source="qbank_likely", retrieval_kind="shortlist",
                    retrieved_qkey="years_experience", retrieval_score=0.7)
_conn.close()

from job_dashboard.api.app import create_app  # noqa: E402

app = create_app(db_path=str(paths.DB), qa_embed=_bow)
