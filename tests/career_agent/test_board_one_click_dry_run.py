from career_agent.boards.profiles import load_boards
from career_agent.boards.run import _beyond_entry


def test_a_dry_run_never_clicks_an_entry_that_is_the_application():
    boards = {b["id"]: b for b in load_boards()}
    for one_click in ("board:instahyre", "board:iimjobs"):
        assert not _beyond_entry(boards[one_click])       # loaded profiles carry default final/advance lists
    assert not _beyond_entry(boards["board:naukri"])      # chat: the bot applies on the last answer (live 2026-10-24)
