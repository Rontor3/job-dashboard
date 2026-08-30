from career_agent.browser.live_view.cdp_bridge import forward_keys


class FakeKB:
    def __init__(self): self.calls = []
    def type(self, t): self.calls.append(("type", t))
    def press(self, k): self.calls.append(("press", k))


class FakePage:
    def __init__(self): self.keyboard = FakeKB()


def test_forward_text_types():
    p = FakePage(); forward_keys(p, "__text__", "Mumbai")
    assert p.keyboard.calls == [("type", "Mumbai")]


def test_forward_key_presses():
    p = FakePage(); forward_keys(p, "__key__", "Enter")
    assert p.keyboard.calls == [("press", "Enter")]


def test_forward_clear_selects_all_and_deletes():
    p = FakePage(); forward_keys(p, "__clear__", "")
    kinds = [c for c in p.keyboard.calls]
    assert ("press", "Backspace") in kinds and any(c[0] == "press" and "A" in c[1] for c in kinds)


def test_drain_dispatches_text_key_clear_to_forward_keys():
    from career_agent.integrations.live_view.session import RemoteSolveSession
    s = RemoteSolveSession(FakePage(), "127.0.0.1", 8765, ttl_s=300,
                           allow_public=False, is_cleared=lambda p: False, interactive=True)
    s._pointer_q.put(("Mumbai", None, "__text__"))
    s._pointer_q.put(("Enter", None, "__key__"))
    s._pointer_q.put(("", None, "__clear__"))
    got = []
    s._drain_pointers(lambda *a: None, {"width": 100, "height": 100},
                      forward_keys=lambda page, kind, val: got.append((kind, val)))
    assert got == [("__text__", "Mumbai"), ("__key__", "Enter"), ("__clear__", "")]
