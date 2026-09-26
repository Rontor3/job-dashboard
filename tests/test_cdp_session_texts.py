import json
from job_dashboard.sources.cdp.session import Capture
from tests.cdp_fakes import FakePage, FakeResponse, make_session


def test_texts_yields_url_status_and_text_for_documents_and_json():
    page = FakePage({"https://x/a": [("https://x/doc1", "<html>hi</html>"), ("https://x/api", {"k": 1}), ("https://other/z", "no")]})
    with make_session(page) as s:
        with s.capture("https://x/") as cap:
            s.goto("https://x/a")
    assert list(cap.texts()) == [("https://x/doc1", 200, "<html>hi</html>"), ("https://x/api", 200, json.dumps({"k": 1}))]


def test_texts_skips_responses_whose_text_raises():
    class Bad(FakeResponse):
        def text(self):
            raise RuntimeError("body gone")
    cap = Capture(FakePage(), ("x",))
    cap.responses = [Bad("x1", "a"), FakeResponse("x2", "ok", 403)]
    assert list(cap.texts()) == [("x2", 403, "ok")]
