"""A Naukri apply reply of 200 that still holds a questionnaire, or an error code, is not an application
(Straive / Infosys / Tata Elxsi counted as submitted 2026-10-25, absent from Naukri's own history)."""
from career_agent.boards.profiles import load_boards
from career_agent.boards.signals import confirmed


class Resp:
    def __init__(self, body, req="applyData={...}", status=200):
        self.url, self.status, self._b = "https://www.naukri.com/cloudgateway-workflow/workflow-services/apply-workflow/v1/apply", status, body
        self.request = type("R", (), {"post_data": req})()
    def json(self): return self._b


NAUKRI = next(b for b in load_boards() if b["id"] == "board:naukri")


def test_a_questionnaire_reply_is_not_a_submit():
    r = Resp({"statusCode": 0, "jobs": [{"jobId": "1", "questionnaire": [{"questionId": "5"}]}]})
    assert not confirmed(NAUKRI, [r], "https://www.naukri.com/job-listings-x-1")


def test_an_error_code_landing_is_not_a_submit():
    assert not confirmed(NAUKRI, [], "https://www.naukri.com/myapply/saveApply?multiApplyResp=%7B%22280926002080%22%3A403031%7D")


def test_the_200_landing_is_a_submit():
    assert confirmed(NAUKRI, [], "https://www.naukri.com/myapply/saveApply?multiApplyResp=%7B%22231026019155%22%3A200%7D")
