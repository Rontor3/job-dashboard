"""Writes one application_qa row per field decision during a run. Best-effort:
a recording failure is logged and never aborts the application."""
from __future__ import annotations

import uuid

from job_dashboard import qa_store


class QARecorder:
    def __init__(self, conn, job_id, run_key=None):
        self.conn, self.job_id = conn, job_id
        self.run_key = run_key or uuid.uuid4().hex

    def _rec(self, ref, label, **fields):
        try:
            qa_store.record(self.conn, job_id=self.job_id, run_key=self.run_key,
                            ref=ref, label=label, **fields)
        except Exception as e:
            print(f"[qa] record failed: {e!r}", flush=True)

    def decision(self, d):
        if d.action == "upload":
            return                      # a résumé file path isn't a question
        self._rec(d.ref, d.label, kind=d.kind, answer=str(d.value),
                  source=d.source, status="filled")

    def needs(self, f):
        self._rec(f.ref, f.label, kind=f.kind, purpose=f.purpose, status="needs_answer")

    def on_draft(self, f, res, filled):
        self._rec(f.ref, f.label, kind=f.kind, purpose=f.purpose, answer=res.get("answer"),
                  source="judgment", status="filled" if filled else "needs_answer",
                  confidence=res.get("confidence"), basis=res.get("basis"),
                  context_json={"prompt": res.get("prompt")},
                  unsupported_claims=res.get("unsupported_company_claims") or [])

    def answered(self, f, answer):
        self._rec(f.ref, f.label, answer=str(answer), source="human", status="answered")
