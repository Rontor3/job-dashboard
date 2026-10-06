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
    a = {"url": "https://www.naukri.com/j", "job_id": 7, "submit": True, "autonomous": False, "probe": False,
         "review": False}
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


def _review_run(monkeypatch, board, decisions):
    import career_agent.boards.run as run_mod
    seen = {}
    monkeypatch.setattr(run_mod, "run_board", lambda p, b, ctx: seen.update(ctx) or
                        {"stopped_reason": "dry_run", "url": "https://x/job", "decisions": decisions})
    lim = Limiter()
    out = apply_mod._run_board(board, "page", _args(review=True), limiter=lim)
    return out, seen, lim


def test_review_fills_but_never_submits_or_counts(monkeypatch):
    form = {**BOARD, "entry": {"submits": "no"}}
    out, seen, lim = _review_run(monkeypatch, form, [{"label": "CTC", "value": "30"}])
    assert seen["do_submit"] is False and out["stopped_reason"] == "ready_for_review" and lim.recorded == []


def test_review_on_one_click_board_hands_the_apply_click_over(monkeypatch):
    one = {**BOARD, "entry": {"submits": "yes"}}
    out, _, _ = _review_run(monkeypatch, one, [])
    assert out["stopped_reason"] == "apply_is_one_click"



def test_existing_tab_is_reused_only_for_the_same_job():
    new = NS(url="about:blank")
    same = NS(url="https://in.indeed.com/viewjob?jk=7114886b04ef144a")
    other = NS(url="https://in.indeed.com/viewjob?jk=zzz")
    ctx = NS(pages=[new, other, same])
    assert apply_mod._existing_tab(ctx, new, "https://in.indeed.com/viewjob?jk=7114886b04ef144a") is same
    assert apply_mod._existing_tab(NS(pages=[new, other]), new, same.url) is None


def test_the_assist_reaches_the_board_engine(monkeypatch):
    import career_agent.boards.run as run_mod
    seen = {}
    monkeypatch.setattr(run_mod, "run_board", lambda p, b, ctx: seen.update(ctx) or {"stopped_reason": "probe"})
    marker = object()
    apply_mod._run_board(BOARD, "page", _args(probe=True), limiter=Limiter(), assist=marker)
    assert seen["assist"] is marker


def test_make_assist_is_opt_in_by_flag_or_env(monkeypatch, tmp_path):
    monkeypatch.delenv("CAREER_AGENT_CLAUDE_ASSIST", raising=False)
    assert apply_mod._make_assist(NS(claude_assist=False), str(tmp_path)) is None
    on = apply_mod._make_assist(NS(claude_assist=True), str(tmp_path))
    assert on is not None and on.cap == 5
    monkeypatch.setenv("CAREER_AGENT_CLAUDE_ASSIST", "1")
    assert apply_mod._make_assist(NS(claude_assist=False), str(tmp_path)) is not None


def test_a_run_that_left_the_board_is_not_counted_against_the_boards_daily_cap(monkeypatch):
    import career_agent.boards.run as run_mod
    monkeypatch.setattr(run_mod, "run_board", lambda p, b, ctx: {"stopped_reason": "left_board", "url": "https://x.example/"})
    lim = Limiter()
    out = apply_mod._run_board(BOARD, "page", _args(), limiter=lim)
    assert out["stopped_reason"] == "left_board" and lim.recorded == []


def test_page_at_finds_the_tab_a_board_run_stopped_on():
    a, b = NS(url="https://a.example/"), NS(url="https://b.example/login")
    ctx = NS(pages=[a, b])
    assert apply_mod._page_at(ctx, "https://a.example/", None) is a
    assert apply_mod._page_at(ctx, "https://gone.example/", "fallback") == "fallback"


def test_on_board_uses_the_boards_own_domains():
    from career_agent.boards.profiles import on_board
    board = {"domains": ["indeed.com"]}
    assert on_board("https://smartapply.indeed.com/x", board) and on_board("https://in.indeed.com/viewjob", board)
    assert not on_board("https://jobs.birlasoft.com/job/1", board) and not on_board("https://evilindeed.com/", board)
    assert on_board("https://anything.example/", {})                       # a board without domains is never "left"
