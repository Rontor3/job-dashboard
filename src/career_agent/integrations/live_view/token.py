"""Single-use, expiring token for a remote-solve session, plus URL building.
Pure: the clock is passed in so tests are deterministic."""
from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass
class SolveToken:
    value: str
    expires_at: float
    used: bool = False


def mint_token(ttl_s: int, now: float) -> SolveToken:
    return SolveToken(value=secrets.token_urlsafe(32), expires_at=now + ttl_s)


def check_and_consume(tok: SolveToken, presented: str, now: float) -> bool:
    if tok.used or now >= tok.expires_at:
        return False
    if not secrets.compare_digest(presented, tok.value):
        return False
    tok.used = True
    return True


def build_url(host: str | None, port: int, token: str, allow_public: bool) -> str:
    if not host:
        raise ValueError(
            "no host for the live-view link (set TAILSCALE_HOST or enable a public tunnel)")
    return f"http://{host}:{port}/s/{token}"
