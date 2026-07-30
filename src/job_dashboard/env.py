"""Minimal, zero-dependency ``.env`` loader.

We deliberately do NOT pull in ``python-dotenv`` (not installed, and not worth
a dependency for this). ``load_env_file`` reads simple ``KEY=VALUE`` lines and
populates ``os.environ`` for keys that are not already set.

This is called by the server entry point (``api/serve.py``) BEFORE the app is
imported -- never on plain ``import job_dashboard.api.app``. That separation
matters: several tests are ``skipif not os.getenv("TINYFISH_API_KEY")`` live
smokes, so auto-loading ``.env`` at import time would turn them into real
network calls during ``pytest``. Keeping the load in the server entry only
means test imports stay key-free and the smokes stay skipped.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | os.PathLike = ".env", *, override: bool = False) -> int:
    """Load ``KEY=VALUE`` pairs from ``path`` into ``os.environ``.

    - Blank lines and ``#`` comments are ignored.
    - A leading ``export `` is tolerated.
    - Surrounding single/double quotes on the value are stripped.
    - By default an existing environment variable is NOT overwritten
      (``override=False``), so a value already exported in the shell / CI wins.

    Returns the number of variables actually set. A missing file is a no-op
    (returns 0) -- deployment may rely purely on real environment variables.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return 0

    set_count = 0
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
            set_count += 1
    return set_count
