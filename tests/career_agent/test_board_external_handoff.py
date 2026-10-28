"""An external board leg ("Apply on company site") whose new tab Playwright never sees must still leave the board:
the link's own address is opened in the board tab (Indeed -> careers.wipro.com, live 2026-10-22)."""
from career_agent.boards.run import follow_unseen_handoff

BOARD = {"id": "board:indeed", "domains": ["indeed.com"]}


class FakePage:
    def __init__(self, url):
        self.url, self.visited = url, []

    def goto(self, href, **_):
        self.visited.append(href)
        self.url = "https://careers.wipro.com/job/DATA-SCIENTIST-L3/210192-en_US"   # applystart redirected

    def wait_for_timeout(self, _ms):
        pass


def test_still_on_board_opens_the_link_here():
    page = FakePage("https://in.indeed.com/viewjob?jk=c45fc94859ba33f1")
    href = "https://in.indeed.com/applystart?jk=c45fc94859ba33f1"
    assert follow_unseen_handoff(page, href, BOARD) is page
    assert page.visited == [href]
    assert "wipro.com" in page.url


def test_new_tab_already_off_board_is_left_alone():
    page = FakePage("https://careers.wipro.com/job/x")
    follow_unseen_handoff(page, "https://in.indeed.com/applystart?jk=1", BOARD)
    assert page.visited == []


def test_no_href_does_nothing():
    page = FakePage("https://in.indeed.com/viewjob?jk=1")
    follow_unseen_handoff(page, None, BOARD)
    assert page.visited == []
