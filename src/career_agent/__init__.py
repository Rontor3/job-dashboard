"""Career agent package."""
import os
from pathlib import Path

_local_browsers = Path(__file__).resolve().parents[2] / ".playwright-browsers"
if _local_browsers.is_dir():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_local_browsers))
