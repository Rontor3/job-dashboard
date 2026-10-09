from career_agent.browser.live_view.cdp_bridge import forward_keys, forward_scroll


class FakeKB:
    def __init__(self): self.calls = []
    def type(self, t): self.calls.append(("type", t))
    def press(self, k): self.calls.append(("press", k))


class FakeMouse:
    def __init__(self): self.wheels = []
    def wheel(self, dx, dy): self.wheels.append((dx, dy))


class FakePage:
    viewport_size = {"width": 100, "height": 100}

    def __init__(self):
        self.keyboard, self.mouse = FakeKB(), FakeMouse()

    def wait_for_timeout(self, ms):
        pass


def test_forward_text_types():
    p = FakePage(); forward_keys(p, "__text__", "Mumbai")
    assert p.keyboard.calls == [("type", "Mumbai")]


def test_forward_key_presses():
    p = FakePage(); forward_keys(p, "__key__", "Enter")
    assert p.keyboard.calls == [("press", "Enter")]


def test_forward_clear_selects_all_then_deletes():
    p = FakePage(); forward_keys(p, "__clear__", "")
    (k1, select_all), backspace = p.keyboard.calls
    assert k1 == "press" and select_all.endswith("+A") and backspace == ("press", "Backspace")


def test_forward_scroll_wheels():
    p = FakePage(); forward_scroll(p, 120.0)
    assert p.mouse.wheels == [(0, 120.0)]


def _run_session(page, events):
    from career_agent.integrations.live_view.session import RemoteSolveSession
    s = RemoteSolveSession(page, "127.0.0.1", 8765, ttl_s=300, allow_public=False,
                           is_cleared=lambda p: False, interactive=True)
    for e in [*events, (0.0, 0.0, "__done__")]:
        s._pointer_q.put(e)                      # the live-view server's input sink
    return s.wait_until_cleared(60)


def test_phone_typing_reaches_the_page_keyboard_in_order():
    page = FakePage()
    assert _run_session(page, [("Mumbai", None, "__text__"), ("Enter", None, "__key__"), ("", None, "__clear__")])
    calls = page.keyboard.calls
    assert calls[:2] == [("type", "Mumbai"), ("press", "Enter")]
    assert calls[2][1].endswith("+A") and calls[3] == ("press", "Backspace") and len(calls) == 4


def test_phone_swipe_scrolls_the_page():
    page = FakePage()
    assert _run_session(page, [(150.0, None, "__scroll__")])
    assert page.mouse.wheels == [(0, 150.0)]
