"""Extension point for OPERATOR-SUPPLIED credential handling at an account/login
wall. DISABLED BY DEFAULT.

The agent ships with NO credential logic. It never generates, enters, stores, or
reads a password, and never creates an account on its own — those are actions the
agent does not perform. By default an account/login wall (see `is_auth_wall`) is
handed off to the human, who authenticates (their password manager fills it; the
agent never types it) and the run resumes behind the persisted session.

If you, the operator, choose to automate sign-in for accounts YOU own, you may
provide your own callable with this signature and wire it in (see
`page_prep.clear_auth_wall`). The agent will call it at the wall. Everything
inside it — generating or looking up the secret, filling the field, submitting —
is YOUR code and YOUR responsibility; the value never passes through the agent's
model context. This mirrors the captcha_solver hook: a plug point, not an
implementation. The reference below is intentionally not implemented.
"""
from __future__ import annotations


def provide(page, gate: str) -> bool:
    """OPERATOR-IMPLEMENTED. Clear an account/login wall for an account you own,
    and return True once the page is past it. The agent does not implement this."""
    raise NotImplementedError(
        "No credential provider is configured. The agent does not generate, "
        "enter, store, or read passwords, and does not create accounts. Provide "
        "your own callable for accounts you own, or complete the login via the "
        "human hand-off (the default)."
    )
