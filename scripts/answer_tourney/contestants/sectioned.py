"""sectioned: production's section path (memory/sections.answer_packet) — one local + one Haiku call per packet.

The held-out cases carry no page/section, so a 'section' here is the run of consecutive cases from the same job
(up to MAX_PER_PACKET): the closest stand-in for the fields of one application page. The first case of a packet
answers the whole packet; the rest read the result."""
from __future__ import annotations

import json
from pathlib import Path


class _Cache(dict):
    def get(self, k):
        return dict.get(self, k)


def setup(env):
    from career_agent.memory.factcards import Cards
    env["cards"] = Cards(env["facts"], env["embed"])
    env["plan_cache"] = _Cache()
    env["sec_done"] = {}


def _packet_of(i, cases, size):
    """Indices of the packet containing case i: consecutive cases with the same job, cut every `size`."""
    company = lambda c: (c.get("job") or {}).get("company") or ""
    start = i
    while start > 0 and company(cases[start - 1]) == company(cases[i]):
        start -= 1
    end = start
    while end < len(cases) and company(cases[end]) == company(cases[i]):
        end += 1
    k = start + ((i - start) // size) * size
    return list(range(k, min(k + size, end)))


def answer(env, i, case):
    from career_agent.browser.form_model import Field
    from career_agent.memory import sections as S
    if i not in env["sec_done"]:
        cases = env.get("all_cases") or json.loads((Path(__file__).resolve().parents[1] / "cases.json").read_text())
        env["all_cases"] = cases
        idx = _packet_of(i, cases, S.MAX_PER_PACKET)
        packet = [Field(f"c{j}", cases[j]["kind"], cases[j]["label"], False, list(cases[j]["options"]),
                        section=(cases[j].get("job") or {}).get("company") or "Form") for j in idx]
        res = S.answer_packet(packet, cases[i].get("job") or {}, env["facts"], env["cards"], local_llm=env["llm"],
                              haiku_llm=env["haiku"], cache=env["plan_cache"])
        for j, f in zip(idx, packet):
            env["sec_done"][j] = res.get(f.ref, (None, "no answer"))
    value, note = env["sec_done"][i]
    env["notes"][i] = f"[packet] {note}"[:200]
    return value
