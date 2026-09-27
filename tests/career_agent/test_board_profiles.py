from career_agent.boards.profiles import board_for, json_path, load_boards

IDS = {"board:naukri", "board:linkedin", "board:indeed", "board:iimjobs",
       "board:instahyre", "board:wellfound", "board:workatastartup"}


def test_graph_has_all_boards_with_required_fields():
    boards = load_boards()
    assert {b["id"] for b in boards} == IDS
    for b in boards:
        assert b["archetype"] in ("form", "chat")
        assert b["entry"]["selector"] and b["entry"]["submits"] in ("yes", "no", "maybe")
        assert b["confirm"] and b["daily_cap"] > 0


def test_chat_board_declares_its_chat_selectors_and_parser():
    nk = board_for("https://www.naukri.com/job-listings-x-1")
    assert nk["archetype"] == "chat" and nk["questions"]["parser"] == "naukri"
    assert {"container", "input", "option", "send", "done"} <= set(nk["chat"])


def test_board_for_matches_host_and_subdomains_only():
    assert board_for("https://www.naukri.com/job-listings-x-1")["id"] == "board:naukri"
    assert board_for("https://smartapply.indeed.com/beta/x")["id"] == "board:indeed"
    assert board_for("https://in.indeed.com/viewjob?jk=1")["id"] == "board:indeed"
    assert board_for("https://notnaukri.com/x") is None
    assert board_for("https://boards.greenhouse.io/x") is None
    assert board_for("") is None


def test_challenge_extends_defaults():
    li = board_for("https://www.linkedin.com/jobs/view/1")
    assert "verify you are human" in li["challenge"]
    assert "checkpoint/challenge" in li["challenge"]


def test_json_path():
    o = {"jobs": [{"q": [1, 2]}], "success": True}
    assert json_path(o, "jobs[0].q") == [1, 2]
    assert json_path(o, "jobs[1].q") is None
    assert json_path(o, "success") is True
    assert json_path(None, "a") is None
