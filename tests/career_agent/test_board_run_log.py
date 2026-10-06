import json
from pathlib import Path

from career_agent.boards.run_log import BoardRunLog


class Page:
    def __init__(self, url="https://www.naukri.com/job-1"):
        self.url = url

    def evaluate(self, *_):
        return None

    def wait_for_timeout(self, *_):
        return None

    def screenshot(self, path, full_page=False, **_):
        Path(path).write_bytes(b"png")


def test_pages_and_stop_are_logged_with_screenshots(tmp_path):
    (tmp_path / "perceive7.png").write_bytes(b"stale")             # from an older run
    log = BoardRunLog(str(tmp_path))
    assert not (tmp_path / "perceive7.png").exists()
    page = Page()
    log.page(page)
    log.filled(page)                                       # each page is filled before the driver moves on
    page.url = "https://www.naukri.com/apply/2"
    log.page(page)
    log.finish(page, "needs_human", [{"ref": "a", "label": "Expected CTC"}])
    steps = json.loads((tmp_path / "board_run.json").read_text())
    assert [s["step"] for s in steps] == [0, 1, 2]
    assert [s["kind"] for s in steps] == ["form", "form", "stop"]
    assert steps[-1]["stopped_reason"] == "needs_human"
    assert steps[-1]["pending_human"] == [{"ref": "a", "label": "Expected CTC"}]
    assert all(Path(s["screenshot"]).exists() for s in steps)
    assert steps[1]["url"] == "https://www.naukri.com/apply/2"


def test_without_run_dir_it_is_a_no_op(tmp_path):
    log = BoardRunLog(None)
    log.page(Page())
    log.finish(Page(), "submitted", [])
    assert log.steps == []


def test_a_failing_screenshot_never_breaks_the_run(tmp_path):
    class Broken(Page):
        def screenshot(self, path, full_page=False, **_):
            raise RuntimeError("page closed")

    log = BoardRunLog(str(tmp_path))
    log.page(Broken())
    log.finish(Broken(), "stuck", [])
    steps = json.loads((tmp_path / "board_run.json").read_text())
    assert [s["screenshot"] for s in steps] == [None, None]


def test_screenshot_is_taken_after_the_page_is_filled(tmp_path):
    order = []

    class P(Page):
        def screenshot(self, path, full_page=False, **_):
            order.append(("shot", Path(path).name))
            super().screenshot(path, full_page)

    P.evaluate = lambda self, js: None if js.startswith("window.scrollTo") else 1000   # page height / viewport
    log, page = BoardRunLog(str(tmp_path)), P()
    log.page(page)
    assert order == []                                   # reading the page takes no picture
    order.append(("typed", None))                        # driver.put(...) types the answers
    log.filled(page)
    assert order == [("typed", None), ("shot", "perceive0.png")]
    step = log.steps[0]
    assert step["screenshot"].endswith("perceive0.png") and step["screenshots"] == [step["screenshot"]]
