from career_agent.integrations.telegram.approver import TelegramApprover


class FakeClient:
    def __init__(self, answers): self.answers = answers; self.sent = []
    def send_message(self, text, buttons=None): self.sent.append((text, buttons)); return 1
    def poll_callback(self, timeout_s, valid): return self.answers.pop(0)


def test_submit_returns_true():
    c = FakeClient(["submit"])
    ok = TelegramApprover(c, poll_interval_s=0, deadline_s=10).request("CARD")
    assert ok is True
    assert "CARD" in c.sent[0][0]


def test_skip_returns_false():
    c = FakeClient(["skip"])
    assert TelegramApprover(c, poll_interval_s=0, deadline_s=10).request("CARD") is False


def test_no_answer_before_deadline_returns_false():
    c = FakeClient([None, None, None])  # never answers
    # deadline_s=0 -> the loop makes at most one poll then gives up
    assert TelegramApprover(c, poll_interval_s=0, deadline_s=0).request("CARD") is False
