import json
import sqlite3

from career_agent.memory import qbank

_ATYPES = {"bool", "choice", "text", "number", "date"}
_PROFILE_COLS = {"full_name", "email", "phone", "location", "linkedin_url", "github_url",
                 "portfolio_url", "work_authorization", "years_experience", "willing_to_relocate",
                 "notice_period", "salary_expectation", "current_ctc", "reason_for_change",
                 "gender", "ethnicity", "veteran_status", "disability_status", "postal_code"}


def _conn():
    c = sqlite3.connect(":memory:")
    qbank.ensure(c)
    return c


def test_reseed_keeps_answer_and_normalizes_exact(fake_embed, tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"entries": [{
        "id": "notice_period", "question": "What is your notice period?", "topic": "availability",
        "atype": "number", "wordings": ["Notice period"]}]}))
    c = _conn()
    assert qbank.load_seed(c, fake_embed, seed) == 1
    qbank.set_answer(c, "notice_period", "30")
    qbank.load_seed(c, fake_embed, seed)
    e = qbank.get_entry(c, "notice_period")
    assert e["answer"] == "30" and e["slots"] == [] and e["synonyms"] == {}
    assert qbank.exact(c, "Notice period?") == "notice_period"
    assert len(qbank.wordings(c)) == 2
    assert qbank.seed_if_empty(c, fake_embed, seed) == 0


def test_seed_cannot_steal_a_wording_but_human_repoint_can(fake_embed):
    c = _conn()
    for i in ("a", "b"):
        qbank.upsert_entry(c, {"id": i, "question": f"q {i}", "atype": "text"})
    v = fake_embed(["Where do you live?"])[0]
    assert qbank.add_wording(c, "Where do you live?", "a", v, "seed")
    assert not qbank.add_wording(c, "Where do you live?", "b", v, "seed")
    assert qbank.exact(c, "where do you live") == "a"
    qbank.add_wording(c, "Where do you live?", "b", v, "human", replace=True)
    assert qbank.exact(c, "where do you live") == "b"
    assert qbank.wordings_for(c, "b") == ["Where do you live?"]


def test_superseded_entries_are_invisible(fake_embed):
    c = _conn()
    qbank.upsert_entry(c, {"id": "x", "question": "Old?", "atype": "bool"})
    qbank.add_wording(c, "Old?", "x", fake_embed(["Old?"])[0], "seed")
    assert qbank.set_status(c, "x", "superseded")
    assert qbank.exact(c, "Old?") is None and qbank.wordings(c) == [] and qbank.entries(c) == []


def test_add_entry_makes_unique_ids(fake_embed):
    c = _conn()
    a = qbank.add_entry(c, question="Have you used Claude?", kind="radio_group", answer="Yes", embed=fake_embed)
    b = qbank.add_entry(c, question="Have you used Claude?", kind="text", answer="Yes", embed=fake_embed)
    assert (a, b) == ("have_you_used_claude", "have_you_used_claude_2")
    assert qbank.get_entry(c, a)["atype"] == "choice" and qbank.get_entry(c, a)["answer"] == "Yes"


def test_real_seed_file_is_valid(fake_embed):
    raw = json.loads(qbank.SEED_PATH.read_text())["entries"]
    assert len(raw) >= 80
    assert all("answer" not in e for e in raw), "seed must never carry answers"
    assert all(e["atype"] in _ATYPES for e in raw)
    assert {e["profile_ref"] for e in raw if e.get("profile_ref")} <= _PROFILE_COLS
    texts = [qbank.norm(t) for e in raw for t in [e["question"], *e.get("wordings", [])]]
    assert len(texts) == len(set(texts)), "a wording is listed twice"
    assert qbank.load_seed(_conn(), fake_embed) == len(raw)


def test_story_entries_never_match_and_render(fake_embed, tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"entries": [
        {"id": "story_why_startups", "topic": "story", "atype": "text",
         "question": "Why do you want to work at an early-stage startup?"},
        {"id": "story_problems", "topic": "story", "atype": "text",
         "question": "What kinds of problems excite you?"},
        {"id": "notice_period", "topic": "availability", "atype": "number",
         "question": "What is your notice period?"}]}))
    c = _conn()
    qbank.load_seed(c, fake_embed, seed)
    assert qbank.exact(c, "Why do you want to work at an early-stage startup?") is None
    assert {e for _, e, _ in qbank.wordings(c)} == {"notice_period"}
    assert qbank.story_text(c) == ""
    qbank.set_answer(c, "story_why_startups", "I like owning outcomes.")
    assert qbank.story_text(c) == ("Q: Why do you want to work at an early-stage startup?\n"
                                   "A: I like owning outcomes.")


def test_real_seed_has_five_story_prompts():
    raw = json.loads(qbank.SEED_PATH.read_text())["entries"]
    assert sorted(e["id"] for e in raw if e["topic"] == "story") == [
        "story_how_you_work", "story_looking_for", "story_problems",
        "story_proudest_work", "story_why_startups"]


def test_preference_entries_in_seed():
    by = {e["id"]: e for e in json.loads(qbank.SEED_PATH.read_text())["entries"]}
    for eid in ("work_arrangement", "employment_type", "shift_pattern", "relocation_places"):
        assert by[eid]["rule"] == "preference" and by[eid]["synonyms"], eid
    assert "gurugram" in by["relocation_places"]["synonyms"]["India"]
