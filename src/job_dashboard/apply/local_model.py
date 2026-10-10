"""Start Ollama when filling starts, stop it when the queue is done (it holds a lot of RAM).

Only acts when the configured LLM (job_dashboard.llm) IS the local Ollama; with any other provider these are no-ops."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request

from job_dashboard import llm


def _ollama_root() -> str | None:
    cfg = llm.config()
    return cfg.base_url.removesuffix("/v1") if cfg.is_local_ollama else None


def is_up(host: str | None = None) -> bool:
    host = host or _ollama_root()
    if not host:
        return False
    try:
        urllib.request.urlopen(host, timeout=1).close()
        return True
    except Exception:
        return False


def ensure_running(wait_s: int = 25) -> bool:
    """True if WE started it (so the caller may stop it later). Never raises; a failed start just means Claude drafts."""
    if sys.platform != "darwin" or not _ollama_root() or is_up():
        return False
    try:
        if subprocess.run(["open", "-a", "Ollama"], timeout=10, capture_output=True).returncode != 0:
            return False
    except Exception:
        return False
    end = time.monotonic() + wait_s
    while time.monotonic() < end and not is_up():
        time.sleep(1)
    return is_up()


def stop() -> None:
    if _ollama_root():
        subprocess.run(["pkill", "-f", "Ollama.app"], timeout=10)
