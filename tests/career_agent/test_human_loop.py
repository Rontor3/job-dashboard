import threading

from career_agent.integrations.human_loop import HumanLoop


class YesApprover:
    def request(self, card): return True


class FakeNotifier:
    """Stands in for RemoteSolveNotifier: records what it was told and hands
    back an abort Event (pre-set when we want to simulate an Abort tap)."""
    def __init__(self, aborted=False):
        self.started = []
        self.closed = []
        self._ev = threading.Event()
        if aborted:
            self._ev.set()

    def start(self, url, gate, deadline_s):
        self.started.append((url, gate, deadline_s))
        return self._ev

    def close(self, cleared=None):
        self.closed.append(cleared)


class FakeSession:
    def __init__(self, page, cleared=True):
        self._cleared = cleared
        self.closed = False
        self.seen_abort = "unset"

    def start(self): return "http://mac.ts.net:8765/s/abc"

    def wait_until_cleared(self, timeout_s, abort_event=None):
        self.seen_abort = abort_event
        return self._cleared

    def close(self): self.closed = True


def test_approve_delegates():
    assert HumanLoop(YesApprover()).approve("card") is True


def test_remote_solve_without_factory_returns_false():
    # no live-view configured -> caller must degrade to stop-and-report
    hl = HumanLoop(YesApprover(), remote_solve_factory=None)
    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox", notifier=None) is False


def test_remote_solve_notifies_with_gate_and_passes_abort_event():
    box = {}
    def factory(page):
        box["sess"] = FakeSession(page, cleared=True)
        return box["sess"]
    notifier = FakeNotifier()
    hl = HumanLoop(YesApprover(), remote_solve_factory=factory, deadline_s=300)

    ok = hl.remote_solve(page=object(), gate="hcaptcha_image", notifier=notifier)

    assert ok is True
    # the gate type + link + deadline reach the notifier
    assert notifier.started == [("http://mac.ts.net:8765/s/abc", "hcaptcha_image", 300)]
    # the notifier's abort Event is threaded into the wait so Abort can cancel it
    assert box["sess"].seen_abort is notifier._ev
    # outcome reported (cleared) and the session torn down
    assert notifier.closed == [True]
    assert box["sess"].closed is True


def test_remote_solve_aborted_returns_false_and_reports_not_cleared():
    box = {}
    def factory(page):
        box["sess"] = FakeSession(page, cleared=False)  # Abort -> wait returns False
        return box["sess"]
    notifier = FakeNotifier(aborted=True)
    hl = HumanLoop(YesApprover(), remote_solve_factory=factory, deadline_s=300)

    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox", notifier=notifier) is False
    assert notifier.closed == [False]


def test_remote_solve_degrades_when_start_raises_and_still_closes():
    seen = {}
    class BrokenSession:
        def __init__(self, page): pass
        def start(self): raise RuntimeError("port bind failed")
        def wait_until_cleared(self, timeout_s, abort_event=None): return True  # unreached
        def close(self): seen["closed"] = True
    notifier = FakeNotifier()
    hl = HumanLoop(YesApprover(), remote_solve_factory=lambda p: BrokenSession(p))

    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox", notifier=notifier) is False
    assert seen["closed"] is True
    # start() raised before the card was sent -> notifier never started
    assert notifier.started == []


def test_remote_solve_degrades_when_factory_raises():
    def boom(page): raise RuntimeError("cannot detect viewport")
    hl = HumanLoop(YesApprover(), remote_solve_factory=boom)
    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox", notifier=None) is False


def test_remote_solve_without_notifier_still_solves():
    # factory present but no delivery channel -> plain wait, abort_event is None
    sess = FakeSession(object(), cleared=True)
    hl = HumanLoop(YesApprover(), remote_solve_factory=lambda p: sess, deadline_s=300)
    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox", notifier=None) is True
    assert sess.seen_abort is None
