"""A re-run of a job retires the tabs its last run left open, and nothing else (Lingaro: 4 Lever forms after 4 runs)."""
from career_agent.browser.runner import TabLedger, note_left_tabs, retire_left_tabs


class _Page:
    def __init__(self, tid): self.tid, self.closed = tid, False
    def is_closed(self): return self.closed
    def close(self): self.closed = True


class _Ctx:
    def __init__(self, pages): self.pages = pages
    def on(self, *_): pass
    def new_cdp_session(self, p):
        class S:
            def send(_, m): return {"targetInfo": {"targetId": p.tid}}
        return S()


def test_the_last_runs_own_tabs_go_and_others_stay(tmp_path):
    mine, users, other_job = _Page("A"), _Page("U"), _Page("O")
    ctx = _Ctx([mine, users, other_job])
    led = TabLedger(ctx, mine); led.mark_user_owned(users)
    note_left_tabs(led, ctx, tmp_path / "left.json")          # run 1 ends: its form tab A stays for review
    keep = _Page("K")
    ctx.pages.append(keep)
    assert retire_left_tabs(ctx, tmp_path / "left.json", keep=[keep]) == 1
    assert mine.closed and not users.closed and not other_job.closed and not keep.closed
