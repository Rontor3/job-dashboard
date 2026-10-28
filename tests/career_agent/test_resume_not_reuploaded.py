"""A résumé already listed on the page is not attached again (Pretium Workday: 5 copies after 5 runs, 2026-10-26)."""
from career_agent.browser.filler import resume_already_attached


class P:
    def __init__(self, body): self.body = body
    def evaluate(self, js, arg): return arg in self.body


def test_a_listed_resume_counts_as_attached():
    assert resume_already_attached(P("Resume/CV  Rakshit_Singh_Resume.pdf 148.65 KB Successfully Uploaded!"),
                                   "data/resumes/upload/Rakshit_Singh_Resume.pdf")


def test_an_empty_upload_slot_is_not():
    assert not resume_already_attached(P("Resume/CV  Upload a file (5MB max)"), "data/resumes/upload/Rakshit_Singh_Resume.pdf")
