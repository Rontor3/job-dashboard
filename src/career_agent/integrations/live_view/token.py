"""Single-use, expiring token for a remote-solve session, plus URL building.
Pure: the clock is passed in so tests are deterministic."""
from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass

# Tailscale hands out addresses in the CGNAT range 100.64.0.0/10 and MagicDNS
# names under *.ts.net. Those, plus loopback and RFC1918 LAN, count as private.
_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


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


def is_valid(tok: SolveToken, presented: str, now: float) -> bool:
    """Non-consuming check: the token matches and hasn't expired or been
    revoked. Used to gate live-view connections — a phone that reflexively goes
    back/reloads must be able to RECONNECT within the TTL, so we don't burn the
    token on first connect. Still tailnet-only, still TTL-bounded, and the
    session dies on solve/close, so the exposure window is unchanged (<= TTL)."""
    if tok.used or now >= tok.expires_at:
        return False
    return secrets.compare_digest(presented, tok.value)


def _is_private_host(host: str) -> bool:
    """True for tailnet / loopback / LAN hosts — the ones safe to link without
    an explicit public opt-in."""
    h = host.strip().lower()
    if h == "localhost":
        return True
    if h.endswith(".ts.net"):          # Tailscale MagicDNS
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False                   # a non-tailnet hostname → treat as public
    return ip in _TAILSCALE_CGNAT or ip.is_private or ip.is_loopback


def build_url(host: str | None, port: int, token: str, allow_public: bool) -> str:
    if not host:
        raise ValueError(
            "no host for the live-view link (set TAILSCALE_HOST or enable a public tunnel)")
    if not allow_public and not _is_private_host(host):
        raise ValueError(
            f"refusing to build a public live-view link to {host!r} (not on the tailnet); "
            "set REMOTE_SOLVE_ALLOW_PUBLIC=1 to opt in")
    return f"http://{host}:{port}/s/{token}"
