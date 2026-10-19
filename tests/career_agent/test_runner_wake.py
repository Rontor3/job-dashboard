"""A sleeping tab blocks attaching to Chrome: the launcher wakes every tab and tries once more."""
import json

from career_agent.browser import runner


class FakePW:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_wake_tabs_activates_every_page_only(monkeypatch):
    hit = []

    class Resp:
        def __init__(self, body=b"ok"):
            self.body = body

        def read(self):
            return self.body

    def urlopen(url, timeout=None):
        hit.append(url)
        if url.endswith("/json"):
            import io
            return io.BytesIO(json.dumps([{"id": "A", "type": "page"}, {"id": "W", "type": "service_worker"},
                                          {"id": "B", "type": "page"}]).encode())
        return Resp()
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert runner.wake_tabs("http://localhost:9222/") == 2
    assert hit[1:] == ["http://localhost:9222/json/activate/A", "http://localhost:9222/json/activate/B",
                       "http://localhost:9222/json/activate/A"]          # and the user's own tab is put back in front


def test_a_stalled_attach_wakes_the_tabs_and_retries(monkeypatch):
    calls, woke = [], []

    class Ctx:
        def new_page(self):
            return "page"

    class Browser:
        contexts = [Ctx()]

    def attach(pw, url, timeout_ms):
        calls.append(timeout_ms)
        if len(calls) <= 2:
            raise TimeoutError("a sleeping tab")
        return Browser()
    pw = FakePW()
    monkeypatch.setattr(runner, "_attach", attach)
    monkeypatch.setattr(runner, "wake_tabs", lambda url: woke.append(url) or 4)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: type("S", (), {"start": lambda self: pw})())
    out = runner.launch(None, cdp_url="http://localhost:9222")
    assert woke == ["http://localhost:9222"] and len(calls) == 3 and out[2] == "page" and not pw.stopped
