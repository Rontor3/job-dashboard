from types import SimpleNamespace as NS

from career_agent import apply as apply_mod

BOARD = {"id": "board:x", "archetype": "form", "daily_cap": 3}


class Limiter:
    def __init__(self, verdict="ok"):
        self.verdict, self.recorded = verdict, []

    def check(self, domain):
        return self.verdict

    def record(self, domain, outcome):
        self.recorded.append((domain, outcome))


def _args(**kw):
    a = {"url": "https://www.naukri.com/j", "job_id": 7, "submit": True, "autonomous": False, "probe": False}
    return NS(**{**a, **kw})


def test_daily_cap_skips_without_touching_the_page(monkeypatch):
    import career_agent.boards.run as run_mod
    monkeypatch.setattr(run_mod, "run_board", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    out = apply_mod._run_board(BOARD, None, _args(), limiter=Limiter("defer"))
    assert out["stopped_reason"] == "daily_cap" and not out["submitted"]


def test_passes_submit_flags_and_records_outcome(monkeypatch):
    import career_agent.boards.run as run_mod
    seen = {}

    def fake(page, board, ctx):
        seen.update(ctx)
        return {"stopped_reason": "dry_run", "submitted": False}

    monkeypatch.setattr(run_mod, "run_board", fake)
    lim = Limiter()
    apply_mod._run_board(BOARD, "page", _args(), limiter=lim, profile="P")
    assert seen["do_submit"] is True and seen["probe"] is False and seen["job_id"] == 7 and seen["profile"] == "P"
    assert lim.recorded == [("board:x", "dry_run")]


def test_probe_never_submits_and_is_not_recorded(monkeypatch):
    import career_agent.boards.run as run_mod
    seen = {}
    monkeypatch.setattr(run_mod, "run_board", lambda p, b, ctx: seen.update(ctx) or {"stopped_reason": "probe"})
    lim = Limiter("defer")                      # cap reached: probe still allowed, nothing recorded
    apply_mod._run_board(BOARD, "page", _args(probe=True), limiter=lim)
    assert seen["do_submit"] is False and seen["probe"] is True and lim.recorded == []
