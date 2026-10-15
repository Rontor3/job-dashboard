"""wholebank_solo: wholebank without the Haiku cross-check — local model alone, deterministic checks only."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("wholebank_base", Path(__file__).with_name("wholebank.py"))
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)


def setup(env):
    wb.setup(env)
    env["no_cross_check"] = True


answer = wb.answer
