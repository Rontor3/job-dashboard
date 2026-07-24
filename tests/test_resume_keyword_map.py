"""Tests for src/job_dashboard/resume/keyword_map.py.

The integrity-critical case: an injected fake llm proposes a fabricated
tool name absent from the block's own source text. The code-side guard
must reject it and emit a GapKeyword instead — never a Rephrasing that
carries a claim the candidate cannot back up.
"""

from __future__ import annotations

import re
from pathlib import Path

from job_dashboard.resume.keyword_map import (
    GapKeyword,
    LlmProposal,
    Rephrasing,
    _ALLOWED_GENERIC,
    _KNOWN_TOOLS,
    _TOKEN_RE,
    extract_keywords,
    propose_rephrasings,
    simple_deep_rank,
)
from job_dashboard.resume.segments import Segment


def _segment(seg_id: str, text: str, tags: list[str] | None = None, kind: str = "skills") -> Segment:
    return Segment(
        id=seg_id, kind=kind, title=seg_id, tags=tags or [],
        tex_path=Path(f"{seg_id}.tex"), text=text,
    )


def test_valid_rephrasing_reusing_only_block_text_is_accepted():
    """A truthful reword that only reuses words already in the block's own
    text is accepted as a Rephrasing with the llm's confidence tag.

    Note: the guard is intentionally strict about tool-like tokens — it
    checks literal (case-insensitive) presence in source text, not "is
    this a known synonym". So a truthful rephrasing may reorder/re-
    emphasize a tool the block already names, but can't introduce even a
    friendly alternate spelling ("Postgres" for "PostgreSQL") that isn't
    literally there — that's exactly what the fabrication test below
    checks stays rejected.
    """
    segments = [_segment("skills-db", r"\item \textbf{Databases}: PostgreSQL, Redis")]
    jd_text = "Looking for someone with strong Redis experience."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-db",
                jd_keyword="redis",
                proposed_text=r"\item \textbf{Databases}: Redis, PostgreSQL",
                confidence="exact-synonym",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    assert len(rephrasings) == 1
    r = rephrasings[0]
    assert r.block_id == "skills-db"
    assert r.jd_keyword == "redis"
    assert r.confidence == "exact-synonym"
    assert r.needs_interview_prep is False
    assert r.original_text == segments[0].text


def test_transferable_confidence_sets_needs_interview_prep():
    segments = [_segment("skills-cloud", r"\item \textbf{Cloud}: AWS Lambda, DynamoDB")]
    jd_text = "Experience with serverless architecture is a plus."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-cloud",
                jd_keyword="serverless",
                proposed_text=r"\item \textbf{Cloud}: AWS Lambda (serverless), DynamoDB",
                confidence="transferable",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    assert len(rephrasings) == 1
    assert rephrasings[0].needs_interview_prep is True


def test_fabricated_tool_is_rejected_and_becomes_gap_keyword():
    """THE integrity test: the fake llm names "Kafka" — a tool absent from
    the block's own text — even though the JD explicitly asks for Kafka.
    The guard must drop the proposal and emit a GapKeyword, never a
    Rephrasing carrying the fabricated claim."""
    segments = [
        _segment(
            "skills-cloud", r"\item \textbf{Cloud}: AWS Lambda, API Gateway, DynamoDB"
        )
    ]
    jd_text = "Must have hands-on Kafka experience for event streaming."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-cloud",
                jd_keyword="kafka",
                proposed_text=r"\item \textbf{Cloud}: AWS Lambda, API Gateway, DynamoDB, Kafka",
                confidence="equivalent",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    gaps = [g for g in result if isinstance(g, GapKeyword)]

    assert rephrasings == []
    assert any(g.jd_keyword == "kafka" for g in gaps)


def test_no_rephrasing_ever_carries_a_tool_token_absent_from_its_source():
    """Property check across a mixed batch: one truthful proposal, two
    fabricated ones — a lowercase tool ("kafka") and a multi-word product
    ("Big Query") whose words each look generic in isolation. This is the
    blind spot the old capitalized-only classifier missed; the rewritten
    whitelist guard must scan ALL tokens case-insensitively against
    source+generic vocabulary, and separately reject any KNOWN_TOOLS
    phrase absent from the source, regardless of casing or word-splitting.
    """
    segments = [
        _segment("skills-db", r"\item \textbf{Databases}: PostgreSQL, Redis"),
        _segment("skills-cloud", r"\item \textbf{Cloud}: AWS Lambda, DynamoDB"),
    ]
    jd_text = "PostgreSQL and kafka and Big Query experience required."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-db",
                jd_keyword="postgresql",
                proposed_text=r"\item \textbf{Databases}: PostgreSQL (primary), Redis",
                confidence="exact-synonym",
            ),
            LlmProposal(
                block_id="skills-cloud",
                jd_keyword="kafka",
                proposed_text=r"\item \textbf{Cloud}: AWS Lambda, DynamoDB, kafka streaming",
                confidence="transferable",
            ),
            LlmProposal(
                block_id="skills-cloud",
                jd_keyword="bigquery",
                proposed_text=r"\item \textbf{Cloud}: AWS Lambda, DynamoDB, Big Query",
                confidence="equivalent",
            ),
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)
    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    gaps = [g for g in result if isinstance(g, GapKeyword)]

    assert len(rephrasings) == 1
    assert rephrasings[0].jd_keyword == "postgresql"
    assert any(g.jd_keyword == "kafka" for g in gaps)
    assert any(g.jd_keyword == "bigquery" for g in gaps)

    seg_by_id = {s.id: s for s in segments}
    for r in rephrasings:
        source_text = seg_by_id[r.block_id].text
        source_tokens = {t.lower() for t in _TOKEN_RE.findall(source_text)}
        for token in _TOKEN_RE.findall(r.proposed_text):
            word = token.lower()
            # EVERY token, case-insensitively — not just capitalized ones —
            # must trace back to source text or generic vocabulary.
            assert word in source_tokens or word in _ALLOWED_GENERIC, (
                f"fabricated token {word!r} leaked into an accepted Rephrasing"
            )

        proposed_lower = r.proposed_text.lower()
        source_lower = source_text.lower()
        for phrase in _KNOWN_TOOLS:
            pattern = re.compile(
                r"\b" + r"\s+".join(re.escape(p) for p in phrase.split(" ")) + r"\b"
            )
            leaked = pattern.search(proposed_lower) and not pattern.search(source_lower)
            assert not leaked, (
                f"KNOWN_TOOLS phrase {phrase!r} leaked into an accepted Rephrasing"
            )


def test_lowercase_fabricated_tool_rejected():
    """Bypass #1 (closed): a lowercase fabricated tool name ("kafka", not
    "Kafka") must be rejected exactly like a capitalized one — the old
    guard's ``_is_tool_like`` ignored lowercase tokens entirely, letting
    this straight through as "not tool-like"."""
    segments = [
        _segment(
            "skills-cloud", r"\item \textbf{Cloud}: AWS Lambda, API Gateway, DynamoDB"
        )
    ]
    jd_text = "Must have hands-on Kafka experience for event streaming."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-cloud",
                jd_keyword="kafka",
                proposed_text=r"\item \textbf{Cloud}: AWS Lambda, API Gateway, DynamoDB, kafka",
                confidence="equivalent",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    gaps = [g for g in result if isinstance(g, GapKeyword)]

    assert rephrasings == []
    assert any(g.jd_keyword == "kafka" for g in gaps)


def test_multiword_fabricated_tool_rejected():
    """Bypass #2 (closed): "Big Query" splits into "Big" + "Query", each of
    which the old classifier treated as plausible generic English on its
    own. The KNOWN_TOOLS phrase net must catch the multi-word product name
    even when its component words look individually harmless."""
    segments = [
        _segment("skills-data", r"\item \textbf{Data}: Python, SQL, ETL pipelines")
    ]
    jd_text = "Experience with BigQuery for data warehousing is required."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-data",
                jd_keyword="bigquery",
                proposed_text=r"\item \textbf{Data}: Python, SQL, ETL pipelines, Big Query",
                confidence="equivalent",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    gaps = [g for g in result if isinstance(g, GapKeyword)]

    assert rephrasings == []
    assert any(g.jd_keyword == "bigquery" for g in gaps)


def test_capitalized_fabricated_tool_still_rejected():
    """Regression guard: the original capitalized-tool bypass case (Kafka)
    must remain caught by the rewritten whitelist-based guard, not just
    the new lowercase/multi-word cases it was added to close."""
    segments = [
        _segment(
            "skills-cloud", r"\item \textbf{Cloud}: AWS Lambda, API Gateway, DynamoDB"
        )
    ]
    jd_text = "Must have hands-on Kafka experience for event streaming."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-cloud",
                jd_keyword="kafka",
                proposed_text=r"\item \textbf{Cloud}: AWS Lambda, API Gateway, DynamoDB, Kafka",
                confidence="equivalent",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    gaps = [g for g in result if isinstance(g, GapKeyword)]

    assert rephrasings == []
    assert any(g.jd_keyword == "kafka" for g in gaps)


def test_legit_generic_rephrasing_still_accepted():
    """The guard must not be so strict it kills legitimate synonym-style
    rephrasings: reusing the block's own words plus generic tech/resume
    vocabulary (introducing no new proper-noun tool) must still pass."""
    segments = [
        _segment(
            "skills-ml",
            r"\item Built sentence-transformers embeddings pipeline for retrieval",
        )
    ]
    jd_text = "Looking for experience with vector search and semantic retrieval."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-ml",
                jd_keyword="semantic",
                proposed_text=(
                    r"\item Built vector search / semantic retrieval embeddings "
                    r"pipeline using sentence-transformers"
                ),
                confidence="equivalent",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    rephrasings = [r for r in result if isinstance(r, Rephrasing)]
    assert len(rephrasings) == 1
    assert rephrasings[0].jd_keyword == "semantic"


def test_no_llm_means_every_uncovered_keyword_is_a_gap():
    segments = [_segment("skills-db", r"\item \textbf{Databases}: PostgreSQL, Redis")]
    jd_text = "Looking for Kafka and Postgres experience."

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=None)

    assert all(isinstance(r, GapKeyword) for r in result)
    gap_keywords = {g.jd_keyword for g in result}
    assert "kafka" in gap_keywords


def test_keyword_already_present_in_source_text_is_not_a_gap():
    segments = [_segment("skills-db", r"\item \textbf{Databases}: PostgreSQL, Redis")]
    jd_text = "Redis caching experience required."

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=None)

    gap_keywords = {g.jd_keyword for g in result}
    assert "redis" not in gap_keywords


def test_unknown_block_id_from_llm_becomes_gap_not_rephrasing():
    segments = [_segment("skills-db", r"\item \textbf{Databases}: PostgreSQL, Redis")]
    jd_text = "Kafka experience wanted."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="does-not-exist",
                jd_keyword="kafka",
                proposed_text=r"\item Kafka expert",
                confidence="equivalent",
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    assert all(isinstance(r, GapKeyword) for r in result)


def test_invalid_confidence_value_is_rejected_to_gap():
    segments = [_segment("skills-cloud", r"\item \textbf{Cloud}: AWS Lambda, DynamoDB")]
    jd_text = "Kafka experience wanted."

    def fake_llm(segs, jd):
        return [
            LlmProposal(
                block_id="skills-cloud",
                jd_keyword="kafka",
                proposed_text=r"\item \textbf{Cloud}: AWS Lambda, DynamoDB",
                confidence="very-confident",  # not a valid tag
            )
        ]

    result = propose_rephrasings(segments, jd_text, simple_deep_rank, llm=fake_llm)

    assert all(isinstance(r, GapKeyword) for r in result)
    assert any(g.jd_keyword == "kafka" for g in result)
