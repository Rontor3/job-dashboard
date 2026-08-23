"""Compose the human review card from the agent's own fill decisions.

Pure text, built only from decisions — never a screenshot or session data."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision

_FILLED = {"fill", "select", "check_group", "upload"}


def render_card(company: str, role: str, portal: str,
                decisions: list[FillDecision], gate: str) -> str:
    filled = [d for d in decisions if d.action in _FILLED]
    review = [d for d in decisions if d.action == "review"]
    attest = [d for d in decisions if d.action == "attestation"]

    lines = [f"📋 {company} — {role}   ·   {portal}"]
    lines.append("")
    lines.append("FILLED ✅")
    for d in filled:
        lines.append(f"  • {d.label}: {d.value}")
    if not filled:
        lines.append("  (none)")
    if review:
        lines.append("")
        lines.append("REVIEW ⚠️  (needs your input)")
        for d in review:
            lines.append(f"  • {d.label}")
    if attest:
        lines.append("")
        lines.append("ATTESTATIONS 🔒")
        for d in attest:
            lines.append(f"  • {d.label} — NOT ticked")
    lines.append("")
    lines.append(f"GATE: {gate}")
    return "\n".join(lines)
