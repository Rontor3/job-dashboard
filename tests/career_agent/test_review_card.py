from career_agent.orchestrator.mapper import FillDecision
from career_agent.integrations.review_card import render_card


def _d(ref, action, label, value=None):
    return FillDecision(ref=ref, kind="text", label=label, value=value,
                        action=action, source="profile")


def test_card_groups_by_section():
    decisions = [
        _d("#n", "fill", "Full name", "Test User"),
        _d("#s", "review", "Expected salary"),
        _d("#c", "attestation", "I certify this is true"),
    ]
    card = render_card("Acme", "Engineer", "acme.com", decisions, "none")
    head, rest = card.split("FILLED", 1)
    filled, rest = rest.split("REVIEW", 1)
    review, rest = rest.split("ATTESTATIONS", 1)
    attest, gate = rest.split("GATE", 1)
    assert "Acme" in head and "Engineer" in head
    assert "Full name: Test User" in filled and "Expected salary" not in filled and "certify" not in filled
    assert "Expected salary" in review and "certify" not in review
    assert "I certify this is true" in attest and "not ticked" in attest.lower()
    assert gate.strip(" :") == "none"


def test_gate_surfaced_when_challenge_detected():
    card = render_card("Acme", "Eng", "acme.com", [], "cloudflare_interstitial")
    assert "cloudflare_interstitial" in card
