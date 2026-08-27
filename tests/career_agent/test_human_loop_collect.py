from career_agent.integrations.human_loop import HumanLoop
from career_agent.browser.form_model import Field


class YesApprover:
    def request(self, card):
        return True


def _f(ref, label):
    return Field(ref, "text", label, True, [], None, None)


def test_collect_uses_injected_collector():
    fields = [_f("#q", "Why us?")]
    hl = HumanLoop(YesApprover(), collector=lambda fs: {f.ref: "answer:" + f.label for f in fs})
    assert hl.collect(fields) == {"#q": "answer:Why us?"}


def test_collect_without_collector_returns_empty():
    assert HumanLoop(YesApprover()).collect([_f("#q", "Why?")]) == {}
