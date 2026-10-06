from career_agent.integrations.gmail_confirm import match_confirmation as m, search_confirmation


def test_the_real_confirmation_emails_match_and_the_started_email_does_not():
    assert m({"subject": "Rakshit , your application was sent to ZettaMine Labs Pvt. Ltd.", "from": "jobs-noreply@linkedin.com", "snippet": ""},
             "ZettaMine Labs Pvt. Ltd.", "AI Research Engineer")
    assert m({"subject": "Rakshit , your application was sent to Tata Consultancy Services", "from": "jobs-noreply@linkedin.com", "snippet": ""},
             "Tata Consultancy Services", "AI/ML Engineer")
    assert m({"subject": "Thank you for applying", "from": "recruiting@jobalerts.thalesgroup.com",
              "snippet": "We have received your application for the position of Industrial Data & AI Engineer"}, "Thales", "Industrial Data & AI Engineer")
    # "get started" mail from the board about a DIFFERENT, unfinished application: not a confirmation
    assert not m({"subject": "Indeed Application: Senior Agentic AI Engineer", "from": "indeedapply@indeed.com", "snippet": "We'll help you get started"},
                 "Weekday", "Senior Agentic AI Engineer")
    # right words, wrong company
    assert not m({"subject": "Your application was sent to CodeRound AI", "from": "jobs-noreply@linkedin.com", "snippet": ""}, "ZettaMine Labs", "")
    assert not m({"subject": "Complete your application to ZettaMine", "from": "x@y.z", "snippet": ""}, "ZettaMine", "")
    assert not m({"subject": "Weekly digest: 5 jobs for you", "from": "x@y.z", "snippet": "your application received a new view at Acme"}, "Acme", "")


def test_search_reads_metadata_only_and_returns_the_matching_mail():
    calls = []

    class _Req:
        def __init__(self, out): self.out = out
        def execute(self): return self.out

    class _Msgs:
        def list(self, **kw): calls.append(("list", kw)); return _Req({"messages": [{"id": "1"}, {"id": "2"}]})
        def get(self, **kw):
            calls.append(("get", kw))
            subj = "Thank you for applying" if kw["id"] == "2" else "Newsletter"
            return _Req({"snippet": "We have received your application for Data Scientist at Thales", "payload": {"headers": [
                {"name": "Subject", "value": subj}, {"name": "From", "value": "recruiting@jobalerts.thalesgroup.com"},
                {"name": "Date", "value": "Mon, 05 Oct 2026 16:18:24 +0000"}]}})

    class _Users:
        def messages(self): return _Msgs()

    class _Svc:
        def users(self): return _Users()

    hit = search_confirmation(_Svc(), "Thales", "Data Scientist", 1700000000)
    assert hit["id"] == "2" and hit["subject"] == "Thank you for applying" and hit["date"].startswith("2026-10-05")
    assert all(kw.get("format") == "metadata" for name, kw in calls if name == "get")          # never a full body
    assert all(kw["userId"] == "me" for _, kw in calls)


def test_a_company_name_too_generic_to_tell_apart_never_matches():
    from career_agent.integrations.gmail_confirm import company_in
    mail = {"subject": "Application Received - AI Engineer Role", "from": "QuickHyre AI <no-reply@quickhyre.ai>", "snippet": "the team"}
    assert not company_in(mail, "AI") and not company_in(mail, "Team") and not company_in(mail, "Tech")
    assert company_in(mail, "QuickHyre AI") and company_in({"subject": "x", "from": "Thales Group <recruiting@jobalerts.thalesgroup.com>"}, "Thales")
