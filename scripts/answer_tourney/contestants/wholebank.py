"""wholebank: factcard with retrieval removed — the local model reads EVERY fact card (the whole bank + profile)
in one prompt, then the same deterministic checks and the Haiku agreement gate. Values stay local: Haiku still
sees only the question + schema."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("factcard_base", Path(__file__).with_name("factcard.py"))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

NUM_CTX = 16384     # the whole sheet is ~3-5K tokens; Ollama's default window would silently truncate it


def long_llm():
    import requests
    from job_dashboard.letter.draft import make_default_llm

    def post(url, body):
        body = {**body, "options": {**body.get("options", {}), "num_ctx": NUM_CTX}}
        return requests.post(url, json=body, timeout=300).json()
    return make_default_llm(post=post)


def setup(env):
    env["all_cards"] = True
    env["llm"].fn = long_llm()


def answer(env, i, case):
    return fc.answer(env, i, case)
