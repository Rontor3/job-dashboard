"""Start Ollama when filling starts, stop it when the queue is done (it holds a lot of RAM)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def is_up(host: str = _HOST) -> bool:
    try:
        urllib.request.urlopen(host, timeout=1).close()
        return True
    except Exception:
        return False


def ensure_running(wait_s: int = 25) -> bool:
    """True if WE started it (so the caller may stop it later). Never raises; a failed start just means Claude drafts."""
    if sys.platform != "darwin" or is_up():
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
    subprocess.run(["pkill", "-f", "Ollama.app"], timeout=10)
