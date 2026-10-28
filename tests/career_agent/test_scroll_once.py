"""A page is scrolled top->bottom->top once per state: re-reads of an unchanged page stay where they are."""
from career_agent.browser import perception
from career_agent.orchestrator.browser_deps import BrowserDeps


def setup(monkeypatch, fps):
    """fps: the fingerprint the page shows at each call to page_fingerprint, in order."""
    scrolls, seq = [], iter(fps)
    monkeypatch.setattr(perception, "page_fingerprint", lambda page: next(seq))
    monkeypatch.setattr(perception, "snapshot_form", lambda page, scroll=True: scrolls.append(scroll) or [])
    return scrolls


def test_an_unchanged_page_is_scrolled_once(monkeypatch):
    # read fields (scroll, store A) -> read buttons (A: no scroll) -> moved-check (A: no scroll)
    scrolls = setup(monkeypatch, ["A", "A", "A"])
    d = BrowserDeps()
    d.snapshot("page"), d.snapshot("page"), d.snapshot("page")
    assert scrolls == [True, False, False]


def test_a_new_step_or_new_fields_get_their_own_pass(monkeypatch):
    # first read stores A; then the page shows B (next step) -> scroll, store B'; then B' again -> no scroll
    scrolls = setup(monkeypatch, ["A", "B", "B2", "B2"])
    d = BrowserDeps()
    d.snapshot("page"), d.snapshot("page"), d.snapshot("page")
    assert scrolls == [True, True, False]


def test_an_explicit_in_place_read_and_an_unreadable_fingerprint(monkeypatch):
    scrolls = setup(monkeypatch, [None, "A", "A"])
    d = BrowserDeps()
    d.snapshot("page", scroll=False)                       # in place: never scrolls, stores nothing
    d.snapshot("page")                                     # nothing stored yet -> scrolls, stores None
    d.snapshot("page")                                     # stored None is not a match -> scrolls (as before)
    assert scrolls == [False, True, True]


def test_the_fingerprint_covers_each_form_frame_and_skips_captcha_frames():
    class Frame:
        def __init__(self, url, sig):
            self.url, self.sig = url, sig

        def evaluate(self, js):
            if self.sig is None:
                raise RuntimeError("navigating")
            return self.sig

    class Page:
        url = "https://x.myworkdayjobs.com/apply"
        frames = [Frame("https://x.myworkdayjobs.com/apply", "2|a,b"), Frame("https://www.google.com/recaptcha/x", "1|c"),
                  Frame("https://icims.com/form", None)]
    fp = perception.page_fingerprint(Page())
    assert "2|a,b" in fp and "recaptcha" not in fp and "icims.com/form#?" in fp
    Page.frames[0].sig = "3|a,b,c"                         # the step changed inside the frame only
    assert perception.page_fingerprint(Page()) != fp
