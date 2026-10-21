"""RemoteSolveSession.wait_until_cleared honors an abort Event (the phone's
Abort button) — pure, no CDP/network (empty pointer queue never touches the
bridge)."""
import threading

from career_agent.integrations.live_view.session import RemoteSolveSession


class FakePage:
    viewport_size = {"width": 900, "height": 1600}


def _session(is_cleared, ticks):
    seq = iter(ticks)
    return RemoteSolveSession(
        FakePage(), host="mac.ts.net", port=8765, ttl_s=300, allow_public=False,
        is_cleared=is_cleared, clock=lambda: next(seq), sleep=lambda _s: None,
        poll_interval_s=0)


def test_abort_event_cancels_the_wait():
    ev = threading.Event()
    ev.set()  # phone tapped Abort before the first poll
    s = _session(is_cleared=lambda p: False, ticks=[0.0, 0.1, 0.2, 0.3])
    assert s.wait_until_cleared(timeout_s=300, abort_event=ev) is False


def test_clears_when_token_appears_and_no_abort():
    n = {"i": 0}
    def cleared(_p):
        n["i"] += 1
        return n["i"] >= 2  # token shows up on the second poll
    s = _session(is_cleared=cleared, ticks=[0.0, 0.1, 0.2, 0.3, 0.4])
    assert s.wait_until_cleared(timeout_s=300, abort_event=None) is True


def test_times_out_without_abort_or_clear():
    s = _session(is_cleared=lambda p: False, ticks=[0.0, 1.0, 2.0])  # exceeds timeout
    assert s.wait_until_cleared(timeout_s=1, abort_event=threading.Event()) is False
