"""Writes one application_qa row per field decision during a run. Best-effort:
a recording failure is logged and never aborts the application."""
from __future__ import annotations

import uuid

from job_dashboard import qa_store


class QARecorder:
    def __init__(self, conn, job_id, run_key=None):
        self.conn, self.job_id = conn, job_id
        self.run_key = run_key or uuid.uuid4().hex
        self.tracer = None      # f -> retrieval fields (memory.retrieval_trace.explain)
        self.page = None            # form page being answered (set by answer_fields)
        self.promote_embed = None   # set -> human answers also join the Answers tab (qbank_promote)
        self._labels: dict = {}
        self._meta: dict = {}   # ref -> retrieval fields, merged into that ref's row

    def trace_all(self, fields):
        """Snapshot what memory retrieval sees for each field. Called before any
        answer is recorded, so the trace reflects the state retrieval used."""
        if self.tracer is None:
            return
        for f in fields:
            try:
                self._meta[f.ref] = self.tracer(f)
            except Exception as e:
                print(f"[qa] trace failed: {e!r}", flush=True)

    def outcome(self, ref, outcome):
        self._rec(ref, self._labels.get(ref, ref), outcome=outcome)

    def _rec(self, ref, label, **fields):
        self._labels[ref] = label
        fields = {**self._meta.get(ref, {}), **fields}
        if self.page is not None:
            fields["page"] = self.page
        try:
            qa_store.record(self.conn, job_id=self.job_id, run_key=self.run_key,
                            ref=ref, label=label, **fields)
        except Exception as e:
            print(f"[qa] record failed: {e!r}", flush=True)

    def decision(self, d):
        if d.action == "upload":
            return                      # a résumé file path isn't a question
        # A question-bank best guess is on the form but still needs the
        # human's look before submit, so it's listed with the open questions.
        status = "needs_answer" if d.source == "qbank_likely" else "filled"
        self._rec(d.ref, d.label, kind=d.kind, answer=str(d.value),
                  source=d.source, status=status)

    def needs(self, f):
        self._rec(f.ref, f.label, kind=f.kind, purpose=f.purpose, status="needs_answer")

    def on_draft(self, f, res, filled):
        self._rec(f.ref, f.label, kind=f.kind, purpose=f.purpose, answer=res.get("answer"),
                  source="judgment", status="filled" if filled else "needs_answer",
                  confidence=res.get("confidence"), basis=res.get("basis"),
                  context_json={"prompt": res.get("prompt"),
                                **{k: res[k] for k in ("needs", "project_id", "used") if res.get(k) is not None},
                                **({"flags": res["flags"]} if res.get("flags") else {}),
                                **{k: res[k] for k in ("plan_source", "plan_reason") if res.get(k)}},
                  unsupported_claims=res.get("unsupported_company_claims") or [])

    def answered(self, f, answer):
        self._rec(f.ref, f.label, answer=str(answer), source="human", status="answered")
        if self.promote_embed is None:
            return
        try:
            from ..memory.qbank_promote import promote_answer
            if promote_answer(self.conn, f, answer, self.promote_embed):
                print(f"[qa] saved to Answers: {f.label[:60]!r}", flush=True)
        except Exception as e:
            print(f"[qa] could not save to Answers: {e!r}", flush=True)
