"""Resolve the tailnet host for the live-view link."""
from __future__ import annotations

import re
import subprocess

# 100.64.0.0/10 — the CGNAT range Tailscale assigns (second octet 64–127).
_TS_INET = re.compile(r"\binet (100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)\b")


def _iface_tailscale_ip(runner) -> str | None:
    """Fallback: read the tailnet IP straight off the network interface, so the
    live-view works even when the `tailscale` CLI isn't on PATH and the env is
    unset (the interface still carries the 100.64/10 address)."""
    try:
        res = runner(["ifconfig"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    m = _TS_INET.search(getattr(res, "stdout", "") or "")
    return m.group(1) if m else None


def detect_host(settings, runner=subprocess.run) -> str | None:
    if settings.tailscale_host:
        return settings.tailscale_host
    try:
        res = runner(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        if getattr(res, "returncode", 1) == 0:
            line = (res.stdout or "").strip().splitlines()
            if line:
                return line[0].strip()
    except Exception:
        pass
    return _iface_tailscale_ip(runner)
