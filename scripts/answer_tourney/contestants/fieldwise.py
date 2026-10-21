"""fieldwise: production's one-field path (memory/factcards.answer) — local reader + Haiku plan per field, gated."""
from __future__ import annotations


class _Cache(dict):
    def get(self, k):
        return dict.get(self, k)


def setup(env):
    from career_agent.memory.factcards import Cards
    env["cards"] = Cards(env["facts"], env["embed"])
    env["plan_cache"] = _Cache()


def answer(env, i, case):
    from career_agent.memory import factcards
    _, kind, label, options, job, _, _ = case
    value, note = factcards.answer(label, kind, list(options), job, env["facts"], env["cards"],
                                   local_llm=env["llm"], haiku_llm=env["haiku"], cache=env["plan_cache"])
    env["notes"][i] = note[:200]
    return value
