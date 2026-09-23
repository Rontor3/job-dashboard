"""Tests for ExactTechVault — FTS5 over ingredients.json.

Key invariant: returned `source` text must be byte-equal to the stored value.
"""
import json
import pytest
from pathlib import Path
from career_agent.memory.exact_tech import ExactTechVault


@pytest.fixture()
def fixture_ingredients(tmp_path) -> Path:
    data = {
        "version": 1,
        "units": [
            {
                "id": "proj-fraud",
                "type": "project",
                "title": "Health Fraud Pipeline",
                "org": "Acme Insurance",
                "tech": "AWS Lambda DynamoDB Python",
                "tags": ["fraud", "ML", "health", "AWS"],
                "source": "Health Fraud Pipeline — Designed modular ML models for fraud detection, ROC >85.",
            },
            {
                "id": "proj-rec",
                "type": "project",
                "title": "Recommendation Engine",
                "org": "RetailCo",
                "tech": "Spark Kafka Python",
                "tags": ["recommendation", "real-time", "Spark"],
                "source": "Recommendation Engine — Built real-time collaborative filtering with Spark Streaming.",
            },
        ],
    }
    p = tmp_path / "ingredients.json"
    p.write_text(json.dumps(data))
    return p


def test_search_returns_verbatim_source(fixture_ingredients):
    vault = ExactTechVault(fixture_ingredients)
    results = vault.search("fraud ML health")
    assert results, "expected at least one match"
    hit = results[0]
    # Source must be BYTE-EQUAL — no paraphrasing
    expected = "Health Fraud Pipeline — Designed modular ML models for fraud detection, ROC >85."
    assert hit["source"] == expected, f"source was paraphrased or altered: {hit['source']!r}"


def test_search_by_tag(fixture_ingredients):
    vault = ExactTechVault(fixture_ingredients)
    results = vault.search("Spark real-time recommendation")
    assert results[0]["id"] == "proj-rec"


def test_search_empty_keywords_returns_empty(fixture_ingredients):
    vault = ExactTechVault(fixture_ingredients)
    assert vault.search("") == []
    assert vault.search("   ") == []


def test_search_no_match_returns_empty(fixture_ingredients):
    vault = ExactTechVault(fixture_ingredients)
    # Nonsense keyword not in any unit
    results = vault.search("xyzzy quantum blockchain nft")
    assert results == []


def test_search_limit_respected(fixture_ingredients):
    vault = ExactTechVault(fixture_ingredients)
    results = vault.search("Python", limit=1)
    assert len(results) <= 1


def test_real_ingredients_file():
    """Smoke-test against the real ingredients.json in the repo."""
    vault = ExactTechVault()
    results = vault.search("machine learning AWS")
    assert results, "expected at least one hit from real ingredients"
    for r in results:
        assert "source" in r
        assert len(r["source"]) > 10, "source should be a substantive verbatim quote"
