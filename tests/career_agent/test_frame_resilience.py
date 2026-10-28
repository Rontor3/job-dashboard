"""collect_raw survives a hostile frame landscape: a frame that dies mid-scan is
skipped and logged instead of killing the snapshot (live class H 2026-10-20:
a LinkedIn job view with 14 opaque frames died mid-snapshot, no result row
written), and opaque widget frames can't flood the primary fields (class A:
recaptcha/api2 junk and nav-button soup inside the page's frames). Offline:
fake frames, no Playwright."""
from collections import Counter

from career_agent.browser.perception import collect_raw, is_denied_frame


def _row(kind, label, i):
    return {"kind": kind, "label": label, "ref": f"#r{i}"}


def _field_rows(n):
    """n labelled text fields + a button — a real form, reads whole."""
    rows = [_row("text", f"Question {i}", i) for i in range(n)]
    rows.append(_row("button", "Apply", n))
    return rows


def _junk_rows(n):
    """n nav buttons — widget junk, never looks_like_application."""
    return [_row("button", "Menu item", i) for i in range(n)]


class _FakeBox:
    def bounding_box(self): return {"width": 500, "height": 300}
    def is_visible(self): return True


class _Frame:
    def __init__(self, url, rows=None, die=None):
        self.url = url
        self.rows = rows or []
        self.die = die
    def wait_for_load_state(self, *a, **k): pass
    def frame_element(self): return _FakeBox()
    def evaluate(self, js, arg=None):
        if arg is not None:
            return []                       # the section pass: nothing to add here
        if self.die:
            raise self.die("Target crashed")
        return self.rows


def _page(*frames):
    fs = list(frames)
    class _Page:
        frames = fs
    return _Page()


def test_a_dieing_frame_is_skipped_and_logged_not_fatal(capsys):
    main, dead, sibling = _Frame("https://acme.com/jobs", _field_rows(3)), \
        _Frame("https://ad.widget.example/feed", _junk_rows(5), die=RuntimeError), \
        _Frame("https://boards.greenhouse.io/embed/job_app", _field_rows(2))
    out = collect_raw(_page(main, dead, sibling))
    assert [r["ref"] for r in out] == ["#r0", "#r1", "#r2", "#r3", "f2@@#r0", "f2@@#r1", "f2@@#r2"]
    assert "frame 1 dead: RuntimeError" in capsys.readouterr().out


def test_opaque_script_frames_are_denied_like_the_rest():
    for url in ("javascript:void(0)", "javascript:''", "blob:https://acme.com/uuid",
                "data:text/html,<iframe>", "about:blank", ""):
        assert is_denied_frame(url), url
    assert not is_denied_frame("about:srcdoc")          # an embedded document may hold the form


def test_widget_junk_frames_cannot_flood_the_primary_fields(capsys):
    main = _Frame("https://acme.com/jobs", _field_rows(4))           # 4 questions + its button
    junk = [_Frame(f"https://widget{x}.example/feed", _junk_rows(40)) for x in range(1, 7)]
    out = collect_raw(_page(main, *junk))
    assert [r["ref"] for r in out[:5]] == [f"#r{i}" for i in range(5)]   # main whole, first
    per_frame = Counter(r["ref"].split("@@")[0] for r in out[5:])
    assert set(per_frame) == {"f1", "f2", "f3", "f4", "f5"}          # f6 contributed nothing at all
    assert all(v <= 12 for v in per_frame.values())                  # ≤12 fields each
    assert sum(per_frame.values()) <= 60                             # ≤60 in aggregate
    assert "junk capped" in capsys.readouterr().out


def test_main_frame_rows_have_unconditional_priority():
    main = _Frame("https://acme.com/jobs", _junk_rows(200))          # even a flat soup: never bounded
    junk = _Frame("https://widget.example/feed", _junk_rows(40))
    out = collect_raw(_page(main, junk))
    assert len(out) == 200 + 12                                      # main whole + the frame's bound


def test_an_unlisted_real_embedded_form_is_read_whole():
    # a company's own iframe (not in ATS_FRAME_HOSTS) with 20 real fields: not junk,
    # so the heap bound must not truncate it (only the trusted-host lists miss it).
    main = _Frame("https://careers.acme.com/apply", _field_rows(2))
    embed = _Frame("https://hr.acme.com/apply/embed", _field_rows(20))
    out = collect_raw(_page(main, embed))
    assert len(out) == 24                                            # 3 main + 21 embed, none dropped
