"""Tests for the zero-dependency .env loader (job_dashboard.env)."""

import os

from job_dashboard.env import load_env_file


def test_loads_simple_pairs(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "TINYFISH_API_KEY=sk-abc123\n"
        "export OLLAMA_HOST='http://localhost:11434'\n"
        'QUOTED="with spaces"\n'
    )
    for k in ("TINYFISH_API_KEY", "OLLAMA_HOST", "QUOTED"):
        monkeypatch.delenv(k, raising=False)

    n = load_env_file(env)

    assert n == 3
    assert os.environ["TINYFISH_API_KEY"] == "sk-abc123"
    assert os.environ["OLLAMA_HOST"] == "http://localhost:11434"
    assert os.environ["QUOTED"] == "with spaces"


def test_does_not_override_existing_env_by_default(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("TINYFISH_API_KEY=from-file\n")
    monkeypatch.setenv("TINYFISH_API_KEY", "from-shell")

    n = load_env_file(env)

    assert n == 0
    assert os.environ["TINYFISH_API_KEY"] == "from-shell"  # shell wins


def test_override_true_replaces(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("TINYFISH_API_KEY=from-file\n")
    monkeypatch.setenv("TINYFISH_API_KEY", "from-shell")

    load_env_file(env, override=True)

    assert os.environ["TINYFISH_API_KEY"] == "from-file"


def test_missing_file_is_noop(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == 0
