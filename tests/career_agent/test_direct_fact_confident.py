"""Two readers agreeing on a bare fact read is confident; a derived plan stays likely (2026-10-25)."""
from career_agent.memory.qbank_memory import _DIRECT_FACT


def test_bare_fact_read_is_direct():
    assert _DIRECT_FACT.match('agree [full_name] | {"fact": "full_name"}')
    assert _DIRECT_FACT.match('agree [phone] | {"fact": "phone", "field": "number"}')


def test_derived_or_one_reader_is_not():
    assert not _DIRECT_FACT.match('agree [citizenship] | {"fact": "location", "from": "country"}')
    assert not _DIRECT_FACT.match('plan only (local none) | {"fact": "phone"}')
