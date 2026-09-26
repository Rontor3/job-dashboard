"""Confirmation / challenge / logged-out tells, one case per board, from the
2026-09-26/27 live human-apply traces."""
from types import SimpleNamespace as NS

from career_agent.boards.profiles import board_for
from career_agent.boards.signals import confirmed, is_challenge, is_logged_out


def R(url, body=None, req="", status=200):
    def _json():
        if body is None:
            raise ValueError("not json")
        return body
    return NS(url=url, status=status, request=NS(post_data=req), json=_json)


def B(host):
    return board_for(f"https://www.{host}/job/1")


NK = "https://www.naukri.com/cloudgateway-workflow/workflow-services/apply-workflow/v1/apply"


def test_naukri_instant_apply_and_chat_final_confirm():
    b = B("naukri.com")
    assert confirmed(b, [R(NK, {"jobs": [{"message": "You have successfully applied to this job."}]})])
    assert confirmed(b, [R(NK, {}, req='{"strJobsarr":["1"],"applyData":{"1":{"answers":{}}}}')])


def test_naukri_questionnaire_response_alone_is_not_applied():
    b = B("naukri.com")
    assert not confirmed(b, [R(NK, {"jobs": [{"questionnaire": [{"questionId": "1"}]}]},
                               req='{"strJobsarr":["1"],"flowtype":"show"}')])


def test_linkedin_easyapply_submit_only():
    b = B("linkedin.com")
    u = "https://www.linkedin.com/flagship-web/rsc-action/actions/server-request?sduiid=x"
    assert confirmed(b, [R(u, req='{"requestId":"com.linkedin.sdui.requests.jobseeker.easyapply.submit"}')])
    assert not confirmed(b, [R(u, req='{"requestId":"com.linkedin.sdui.infra.register.cooloff.activity"}')])
    assert not confirmed(b, [R(u, req='{"requestId":"x.easyapply.submit"}', status=500)])


def test_indeed_submit_application_mutation():
    b = B("indeed.com")
    assert confirmed(b, [R("https://apis.indeed.com/graphql", req='{"operationName":"SubmitApplication"}')])
    assert not confirmed(b, [R("https://apis.indeed.com/graphql", req='{"operationName":"ResumeSection"}')])


def test_iimjobs_apply_call_or_applied_page():
    b = B("iimjobs.com")
    assert confirmed(b, [R("https://gladiator.iimjobs.com/job/apply?jobcode=1736030", req='{"coverLetter":1}')])
    assert confirmed(b, [], "https://www.iimjobs.com/job/applied?ref=jd&jobId=1736030")
    assert not confirmed(b, [], "https://www.iimjobs.com/j/amgen-1734723")


def test_instahyre_success_flag():
    b = B("instahyre.com")
    u = "https://www.instahyre.com/api/v1/candidate_opportunities/candidate_matching/apply"
    assert confirmed(b, [R(u, {"success": True, "opp_id": 1})])
    assert not confirmed(b, [R(u, {"success": False})])


def test_wellfound_create_job_application():
    b = B("wellfound.com")
    assert confirmed(b, [R("https://wellfound.com/graphql", req='{"operationName":"CreateJobApplication"}')])
    assert not confirmed(b, [R("https://wellfound.com/graphql", req='{"operationName":"TrackView"}')])


def test_nothing_captured_is_not_confirmed():
    assert not confirmed(B("naukri.com"), [])


def test_challenge_and_logged_out_tells():
    li, wf = B("linkedin.com"), B("wellfound.com")
    assert is_challenge(li, "https://www.linkedin.com/checkpoint/challenge/x", "")
    assert is_challenge(li, "https://x", "Please verify you are human")
    assert not is_challenge(li, "https://www.linkedin.com/jobs/view/1", "Easy Apply")
    assert is_logged_out(wf, "https://wellfound.com/jobs/1", "Full Name* Email* Set a Password*")
    assert not is_logged_out(wf, "https://wellfound.com/jobs/1", "Send application")
