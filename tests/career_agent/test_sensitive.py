from types import SimpleNamespace as NS

import pytest

from career_agent.browser.form_model import Field, guess_purpose
from career_agent.integrations.escalation import EscalationCollector
from career_agent.integrations.telegram.collector import TelegramCollector
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.memory.qbank_promote import promote_answer
from career_agent.orchestrator import graph as graph_mod
from career_agent.orchestrator.sensitive import is_sensitive, split_sensitive


def _f(label, ref="#a", required=True, kind="text", description=""):
    return Field(ref, kind, label, required, [], None, guess_purpose(label, kind), description)


@pytest.mark.parametrize("label", [
    "Bank account number", "Account Number", "IFSC code", "Bank name and branch", "Account holder name",
    "Your bank details", "IBAN", "SWIFT / BIC", "Routing number", "Sort code",
    "Credit card number", "Debit card", "CVV", "UPI ID", "PAN number", "PAN card", "Aadhaar number",
    "Aadhar", "UAN number", "Social Security Number", "SSN", "National Insurance number", "Tax ID",
    "Passport number", "Driver's licence number", "National ID number", "Voter ID",
])
def test_bank_and_id_details_are_sensitive(label):
    assert is_sensitive(_f(label)), label


@pytest.mark.parametrize("label", [
    "Full name", "Phone number", "Expected CTC", "Current CTC (in LPA)", "Notice period", "Date of birth",
    "Gender", "Postal code", "LinkedIn profile", "Why do you want to join us?", "Create an account",
    "Have you worked at a bank before?", "Company", "Years of experience with Python",
    "I agree to the privacy policy", "Are you a PAN-India candidate?", "Passport (do you hold one?)",
])
def test_ordinary_fields_are_not(label):
    assert not is_sensitive(_f(label)), label


def test_the_help_text_counts_too():
    assert is_sensitive(_f("Enter number", description="Your bank account number for payroll"))


def test_split_keeps_order_and_separates():
    a, b, c = _f("Full name", "#1"), _f("IFSC code", "#2"), _f("Phone", "#3")
    safe, blocked = split_sensitive([a, b, c])
    assert [f.ref for f in safe] == ["#1", "#3"] and [f.ref for f in blocked] == ["#2"]


# ---- the career-site graph -------------------------------------------------
class Deps:
    def __init__(self):
        self.filled = []

    def fill(self, page, decisions):
        self.filled.append(decisions)


def _state(fields):
    return {"steps": 0, "max_steps": 5, "stopped_reason": None, "decisions": [],
            "form": [graph_mod._f2d(f) for f in fields]}


def _cfg(deps):
    return {"configurable": {"page": NS(), "deps": deps, "profile": CandidateProfile(contact={"full_name": "R"}),
                             "judge_fn": None, "learn": None, "qa": None}}


def test_graph_stops_on_a_required_bank_field_without_filling_or_asking():
    deps = Deps()
    out = graph_mod.fill_node(_state([_f("Full name", "#n"), _f("Bank account number", "#b")]), _cfg(deps))
    assert out["stopped_reason"] == "sensitive_field" and deps.filled == []
    assert [d["label"] for d in out["pending_human"]] == ["Bank account number"]
    assert graph_mod._route_fill({**_state([]), **out}) == graph_mod.END      # never reaches the human gate


def test_graph_ignores_an_optional_bank_field_and_fills_the_rest():
    deps = Deps()
    out = graph_mod.fill_node(_state([_f("Full name", "#n", required=False), _f("PAN number", "#p", required=False)]),
                              _cfg(deps))
    assert not out.get("stopped_reason") and out["pending_human"] == []
    assert [d.ref for d in deps.filled[0]] == ["#n"]


# ---- second lines of defence ----------------------------------------------
class Client:
    def __init__(self):
        self.sent, self.replies = [], ["12345"]

    def send_message(self, text, buttons=None):
        self.sent.append(text)

    def poll_text(self, timeout_s):
        return self.replies.pop(0) if self.replies else None

    def drain(self):
        pass


def test_telegram_never_asks_for_bank_or_id_details():
    client = Client()
    got = TelegramCollector(client, sleep=lambda s: None, poll_interval_s=1)(
        [_f("Bank account number", "#b"), _f("Expected CTC?", "#c")])
    assert got == {"#c": "12345"}
    assert not any("Bank account" in m for m in client.sent)


def test_live_escalation_never_asks_either():
    client = Client()
    inner = TelegramCollector(client, sleep=lambda s: None, poll_interval_s=1)
    notes = []
    col = EscalationCollector(inner, client, context_fn=None, wait_s=120, notify=notes.append)
    assert col([_f("Aadhaar number", "#a")]) == {}
    assert client.sent == []
    assert not any("Aadhaar" in n for n in notes)


def test_a_human_reply_about_such_a_field_is_never_saved_to_the_answers(tmp_path, fake_embed):
    from job_dashboard import qa_store
    from job_dashboard.db import init_db
    from career_agent.memory import qbank
    conn = init_db(str(tmp_path / "t.db"))
    qa_store.ensure(conn)
    qbank.ensure(conn)
    before = len(qbank.entries(conn))
    assert promote_answer(conn, _f("Bank account number"), "000111222", fake_embed) is None
    assert len(qbank.entries(conn)) == before
