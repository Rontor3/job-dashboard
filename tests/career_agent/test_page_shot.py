from career_agent.browser.page_shot import capture_page


class _Page:
    def __init__(self, height, view=800): self.h, self.v, self.shots, self.y = height, view, [], 0
    def wait_for_timeout(self, ms): pass

    def evaluate(self, js):
        if js.startswith("window.scrollTo"):
            self.y = int(js.split(",")[1].strip(" )"))
            return None
        return self.v if "innerHeight" in js else self.h

    def screenshot(self, path, full_page, timeout):
        self.shots.append((path.rsplit("/", 1)[-1], full_page, self.y))
        open(path, "wb").write(b"x")


def test_short_page_is_one_full_page_shot(tmp_path):
    p = _Page(2000)
    assert capture_page(p, str(tmp_path / "perceive3")) == [str(tmp_path / "perceive3.png")]
    assert p.shots == [("perceive3.png", True, 0)]


def test_long_page_is_scrolled_segments_capped(tmp_path):
    p = _Page(20000)
    paths = capture_page(p, str(tmp_path / "perceive0"), max_full=6000, max_parts=6)
    assert [x.rsplit("/", 1)[-1] for x in paths] == ["perceive0.png"] + [f"perceive0_{i}.png" for i in range(2, 7)]
    assert all(not full for _, full, _ in p.shots)                      # viewport shots, not a 20000px image
    ys = [y for _, _, y in p.shots]
    assert ys[0] == 0 and all(0 < b - a < p.v for a, b in zip(ys, ys[1:]))   # each shot overlaps the last


def test_a_long_page_stops_once_the_bottom_is_captured(tmp_path):
    p = _Page(7000)
    paths = capture_page(p, str(tmp_path / "perceive0"), max_full=6000, max_parts=20)
    ys = [y for _, _, y in p.shots]
    assert ys[-1] + p.v >= p.h and len(paths) == len(ys) < 20
    assert ys[-2] + p.v < p.h                                           # no extra shot past the bottom


def test_a_failing_screenshot_never_raises(tmp_path):
    class Boom(_Page):
        def screenshot(self, *a, **k): raise TimeoutError
    assert capture_page(Boom(100), str(tmp_path / "x")) == []


def test_stale_parts_from_a_longer_earlier_capture_are_removed(tmp_path):
    (tmp_path / "perceive1_4.png").write_bytes(b"old")
    capture_page(_Page(500), str(tmp_path / "perceive1"))
    assert not (tmp_path / "perceive1_4.png").exists()
