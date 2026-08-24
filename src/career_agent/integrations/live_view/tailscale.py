"""Resolve the tailnet host for the live-view link."""
from __future__ import annotations

import subprocess


def detect_host(settings, runner=subprocess.run) -> str | None:
    if settings.tailscale_host:
        return settings.tailscale_host
    try:
        res = runner(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if getattr(res, "returncode", 1) != 0:
        return None
    line = (res.stdout or "").strip().splitlines()
    return line[0].strip() if line else None
