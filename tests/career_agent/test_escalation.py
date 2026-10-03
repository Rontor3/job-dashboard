from career_agent.browser.form_model import Field
from career_agent.integrations.escalation import EscalationCollector, build_context
from career_agent.integrations.park import park_human
from career_agent.integrations.telegram.collector import TelegramCollector


def _f(ref, label, kind="text"):
    return Field(ref, kind, label, True, [], None, None)


class Client:
    """Scripted Telegram: poll_text pops replies; None = nothing arrived."""

    def __init__(self, replies):
        self.sent, self.replies = [], list(replies)

    def send_message(self, text, buttons=None):
        self.sent.append(text)
        return len(self.sent)

    def poll_text(self, timeout_s):
        return self.replies.pop(0) if self.replies else None

    def drain(self):
        pass


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s or 1


JOB = {"title": "ML Engineer", "company": "Acme AI", "description": "We build agents.\nYou will ship models."}
RES = [{"title": "About Acme", "source_url": "https://acme.ai/about", "summary": "Acme makes agent tooling."}]


def _collector(replies, wait_s=60, job=JOB, res=RES):
    clock = Clock()
    client = Client(replies)
    inner = TelegramCollector(client, sleep=clock.sleep, poll_interval_s=2)
    notes = []
    col = EscalationCollector(inner, client, context_fn=lambda: build_context(job, res),
                              wait_s=wait_s, notify=notes.append, clock=clock)
    return col, client, notes


def test_build_context_has_jd_then_company_page():
    jd, company = build_context(JOB, RES)
    assert "ML Engineer" in jd and "Acme AI" in jd and "ship models" in jd
    assert "About Acme" in company and "https://acme.ai/about" in company and "agent tooling" in company
    assert build_context({"title": "t", "company": "c", "description": ""}, [])[1] == ""


def test_context_is_sent_first_and_once_then_questions_are_answered_live():
    col, client, notes = _collector(["20 LPA", "30 days"])
    out = col([_f("a", "Expected CTC?")])
    assert out == {"a": "20 LPA"}
    assert "Role context" in client.sent[0] or "ML Engineer" in client.sent[0]
    assert "About Acme" in client.sent[1]
    assert "Expected CTC?" in client.sent[2]
    sent_before = len(client.sent)
    out2 = col([_f("b", "Notice period?")])
    assert out2 == {"b": "30 days"}
    assert not any("ML Engineer" in m and "We build agents" in m for m in client.sent[sent_before:])   # no 2nd JD


def test_unanswered_questions_time_out_and_are_parked_with_one_note():
    col, client, notes = _collector([], wait_s=20)
    assert col([_f("a", "Expected CTC?"), _f("b", "Notice period?")]) == {}
    assert len(notes) == 1 and "2 question(s)" in notes[0] and "tracker" in notes[0]


def test_one_shared_deadline_not_one_per_question():
    col, client, notes = _collector([], wait_s=20)
    col([_f(str(i), f"Question {i}?") for i in range(6)])
    asked = [m for m in client.sent if "Question" in m]
    assert len(asked) < 6                       # later ones were not asked once the time was up
    assert len(notes) == 1 and "6 question(s)" in notes[0]


def test_already_asked_fields_are_not_asked_again():
    col, client, notes = _collector([], wait_s=10)
    col([_f("a", "Expected CTC?")])
    n = len(client.sent)
    assert col([_f("a", "Expected CTC?")]) == {}
    assert len(client.sent) == n


def test_context_failure_never_blocks_the_questions():
    clock = Clock()
    client = Client(["20 LPA"])
    inner = TelegramCollector(client, sleep=clock.sleep, poll_interval_s=2)

    def boom():
        raise RuntimeError("db locked")

    col = EscalationCollector(inner, client, context_fn=boom, wait_s=60, notify=None, clock=clock)
    assert col([_f("a", "Expected CTC?")]) == {"a": "20 LPA"}


def test_context_label_reaches_the_inner_collector_and_events_are_exposed():
    col, client, _ = _collector(["20 LPA"])
    col.context = "Naukri — ML Engineer"
    col([_f("a", "Expected CTC?")])
    assert "Naukri — ML Engineer" in client.sent[-1]
    assert col._last_events == {"a": "approve"}


def test_park_human_uses_live_telegram_when_given_a_collector_and_a_wait():
    client = Client(["20 LPA"])
    inner = TelegramCollector(client, sleep=lambda s: None, poll_interval_s=1)
    human = park_human(notify=None, telegram=inner, client=client, wait_s=120,
                       context_fn=lambda: build_context(JOB, RES))
    assert human.collect([_f("a", "Expected CTC?")]) == {"a": "20 LPA"}
    assert human.approve("submit?") is False                 # submitting stays behind auto-submit
    assert park_human(notify=None, telegram=inner, client=client, wait_s=0).collector.parks is True
