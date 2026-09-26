class FakeResponse:
    def __init__(self, url, body, status=200):
        self.url, self._body, self.status = url, body, status

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakePage:
    """script: {url_or_prefix*: [(response_url, body), ...]} fired on goto."""

    def __init__(self, script=None, text="", status=200):
        self.script, self.text, self.status = script or {}, text, status
        self.url, self.visited, self.handlers, self.closed = "", [], [], False

    def on(self, event, fn):
        assert event == "response"
        self.handlers.append(fn)

    def remove_listener(self, event, fn):
        self.handlers.remove(fn)

    def goto(self, url, wait_until=None):
        self.url = url
        self.visited.append(url)
        for key, resps in self.script.items():
            if key == url or (key.endswith("*") and url.startswith(key[:-1])):
                for ru, body in resps:
                    for h in list(self.handlers):
                        h(FakeResponse(ru, body))
        return FakeResponse(url, None, self.status)

    def evaluate(self, js):
        return self.text

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        self.closed = True


def make_session(page, **kw):
    from job_dashboard.sources.cdp.session import CdpSession
    closed = []
    s = CdpSession("http://x", max_loads=kw.pop("max_loads", 50), nap=lambda: None,
                   connect=lambda url: (page, lambda: closed.append(1)), **kw)
    s.closed = closed
    return s
