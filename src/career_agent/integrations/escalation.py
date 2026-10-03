"""Real-time Telegram escalation for queued (--park) runs.

When the answer ladder is not confident about a question, the run asks the
human on Telegram — job description and company page first, so there is context
before replying — then waits for the answer under ONE shared deadline for the
whole batch. Questions still unanswered when it runs out are left open: the run
ends needs_human, the job is parked as Failed, and the questions wait on the
tracker (application_qa already holds them). Never raises.
"""
from __future__ import annotations

import time

_JD_CHARS = 1500
_ABOUT_CHARS = 900
_MIN_ASK_S = 30            # don't start a question with less than this left


def build_context(job: dict | None, resources: list[dict] | None, jd_text: str | None = None) -> tuple[str, str]:
    """(job-description message, company-page message). The second is "" when
    there is nothing on file about the company."""
    job = job or {}
    title, company = job.get("title") or "this role", job.get("company") or "the company"
    body = (job.get("description") or jd_text or "").strip()
    jd = f"📄 {title} at {company}\n\n{body[:_JD_CHARS]}" + ("…" if len(body) > _JD_CHARS else "")
    lines = []
    for r in (resources or [])[:2]:
        head = r.get("title") or r.get("source_url") or ""
        summary = (r.get("summary") or "").strip()[:_ABOUT_CHARS]
        lines.append(f"• {head}\n{r.get('source_url') or ''}" + (f"\n{summary}" if summary else ""))
    return jd, ("🏢 About " + company + "\n\n" + "\n\n".join(lines)) if lines else ""


class EscalationCollector:
    """HumanLoop collector contract (fields -> {ref: value}) over Telegram."""
    parks = True                       # _run_graph stops re-asking once nothing is answered

    def __init__(self, inner, client, context_fn=None, wait_s: int = 600, notify=None, clock=time.monotonic):
        self.inner, self.client = inner, client
        self.context_fn, self.wait_s, self.notify = context_fn, wait_s, notify
        self._clock = clock
        self._sent_context = False
        self._asked: set[str] = set()
        self._started: float | None = None
        self._last_events: dict[str, str] = {}

    # boards.run labels the application ("Naukri — ML Engineer") on the collector
    @property
    def context(self):
        return self.inner.context

    @context.setter
    def context(self, value):
        self.inner.context = value

    @property
    def jd_text(self):
        return getattr(self.inner, "jd_text", None)

    @jd_text.setter
    def jd_text(self, value):
        self.inner.jd_text = value

    def _send_context(self) -> None:
        if self._sent_context:
            return
        self._sent_context = True
        try:
            for msg in (self.context_fn() if self.context_fn else ()):
                if msg:
                    self.client.send_message(msg)
        except Exception as e:
            print(f"[escalation] context not sent ({type(e).__name__})", flush=True)

    def __call__(self, fields) -> dict:
        self._last_events = {}
        fresh = [f for f in fields if f.ref not in self._asked]
        if not fresh:
            return {}
        self._asked.update(f.ref for f in fresh)
        self._send_context()
        if self._started is None:
            self._started = self._clock()
        out: dict = {}
        unanswered = list(fresh)
        for f in fresh:
            left = self.wait_s - (self._clock() - self._started)
            if left < _MIN_ASK_S:
                break
            self.inner.deadline_s = self.inner.text_deadline_s = int(left)
            try:
                got = self.inner([f])
            except Exception as e:
                print(f"[escalation] telegram failed ({type(e).__name__})", flush=True)
                break
            if got.get(f.ref):
                out[f.ref] = got[f.ref]
                self._last_events.update(getattr(self.inner, "_last_events", {}) or {})
                unanswered.remove(f)
        if unanswered:
            self._park(unanswered)
        return out

    def _park(self, left) -> None:
        labels = ", ".join((f.label or f.ref)[:60] for f in left[:6])
        msg = (f"⏸ {len(left)} question(s) parked for {self.context or 'this job'}: {labels}"
               " — answer them on the tracker, then the job re-queues itself.")
        print(f"[escalation] {msg}", flush=True)
        if self.notify:
            try:
                self.notify(msg)
            except Exception:
                pass
