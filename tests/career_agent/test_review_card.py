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
    assert "Acme" in card and "Engineer" in card
    assert "FILLED" in card and "Full name" in card and "Test User" in card
    assert "REVIEW" in card and "Expected salary" in card
    assert "ATTESTATIONS" in card and "not ticked" in card.lower()
    assert "GATE" in card and "none" in card


def test_gate_surfaced_when_challenge_detected():
    card = render_card("Acme", "Eng", "acme.com", [], "cloudflare_interstitial")
    assert "cloudflare_interstitial" in card
