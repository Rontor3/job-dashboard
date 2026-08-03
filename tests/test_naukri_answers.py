import math
from job_dashboard.apply import naukri_answers as na


class FakeEmbedder:
    """Bag-of-words vectors over a tiny vocab so paraphrases that share content
    words land near each other. Deterministic; no model download."""
    VOCAB = ["python", "sql", "experience", "years", "notice", "relocate",
             "salary", "location", "favorite", "color", "blood", "group",
             "proficiency", "worked", "skill", "total", "work"]
    def encode(self, text):
        t = (text or "").lower()
        return [1.0 if w in t else 0.0 for w in self.VOCAB]


def _bank(profile=None, profile_text="Python and SQL. 3 years experience.",
          llm=None):
    pkg = {"profile": profile or {}, "job": {"title": "Data Scientist"},
           "resume": {"pdf_path": "/tmp/r.pdf"}}
    return na.build_answer_bank(pkg, profile_text=profile_text,
                                llm=llm or (lambda p: "3 years of hands-on Python."),
                                embedder=FakeEmbedder())


def test_bank_has_skill_entries_only_for_resume_skills():
    bank = _bank()
    intents = {e.intent for e in bank}
    assert "skill:python" in intents and "skill:sql" in intents
    assert "skill:java" not in intents  # java not in the profile text


def test_bank_has_personal_entry_only_when_field_set():
    bank = _bank(profile={"notice_period": "30 days"})
    intents = {e.intent for e in bank}
    assert "notice_period" in intents
    assert "current_ctc" not in intents  # unset -> no entry


def test_paraphrases_of_python_reuse_the_same_bank_answer():
    bank = _bank()
    emb = FakeEmbedder()
    phrasings = [
        "How many years of experience do you have in Python?",
        "What is your proficiency in Python?",
        "How long have you worked with Python?",
    ]
    results = [na.resolve_answer(q, bank, embedder=emb) for q in phrasings]
    assert all(r.source == "bank" and not r.needs_user for r in results)
    assert len({r.text for r in results}) == 1  # identical, reused answer


def test_skill_not_on_resume_pauses_without_calling_llm():
    calls = []
    bank = _bank(llm=lambda p: calls.append(p) or "should not be used")
    calls.clear()
    r = na.resolve_answer("Are you proficient in Java?", bank, embedder=FakeEmbedder())
    assert r.needs_user and r.flag == "skill_not_on_resume" and r.text == ""


def test_personal_set_returns_profile_value():
    bank = _bank(profile={"notice_period": "30 days"})
    r = na.resolve_answer("What is your notice period?", bank, embedder=FakeEmbedder())
    assert r.source == "profile" and r.text == "30 days" and not r.needs_user


def test_personal_unset_returns_blank_never_a_number_and_no_llm():
    spy = []
    bank = _bank(profile={}, llm=lambda p: spy.append(p) or "99 LPA")
    spy.clear()
    r = na.resolve_answer("What is your current CTC?", bank, embedder=FakeEmbedder())
    assert r.needs_user and r.flag == "no_stored_value" and r.text == ""
    assert spy == []  # personal facts never sent to the LLM at resolve time


def test_unmatched_question_is_exceptional():
    bank = _bank()
    r = na.resolve_answer("What is your favorite color?", bank, embedder=FakeEmbedder())
    assert r.needs_user and r.flag == "exceptional" and r.text == ""


class MapEmbedder:
    """Maps exact strings to preset vectors; unknown strings -> orthogonal.
    Lets a test force the step-3 cosine path deterministically."""
    def __init__(self, mapping):
        self.mapping = mapping
    def encode(self, text):
        return self.mapping.get(text, [0.0, 0.0, 0.0, 1.0])


def test_semantic_fallback_reuses_skill_entry_for_true_paraphrase():
    # A paraphrase sharing NO skill word or keyword must still reuse the python
    # bank answer via the cosine fallback (step 3) — the core reuse feature.
    q = "Describe your serpent-scripting background."
    emb = MapEmbedder({
        "years of experience with python": [1.0, 0.0, 0.0, 0.0],
        q: [1.0, 0.0, 0.0, 0.0],  # identical vector -> cosine 1.0 >= 0.60
    })
    pkg = {"profile": {}, "job": {"title": "Data Scientist"},
           "resume": {"pdf_path": "/tmp/r.pdf"}}
    bank = na.build_answer_bank(
        pkg, profile_text="Python and SQL. 3 years experience.",
        llm=lambda p: "3 years of hands-on Python.", embedder=emb)
    r = na.resolve_answer(q, bank, embedder=emb)
    assert r.source == "bank" and not r.needs_user and r.text  # reused, not paused


def test_semantic_fallback_never_autofills_a_personal_fact():
    # A personal question phrased outside the keyword list must NOT be fuzzy-
    # matched to a stored personal value — it pauses instead (safety).
    q = "Roughly what compensation are you on right now?"
    emb = MapEmbedder({
        "what is your current ctc salary": [1.0, 0.0, 0.0, 0.0],
        q: [1.0, 0.0, 0.0, 0.0],  # would match IF personal entries were eligible
    })
    pkg = {"profile": {"current_ctc": "12 LPA"}, "job": {},
           "resume": {"pdf_path": "/tmp/r.pdf"}}
    bank = na.build_answer_bank(pkg, profile_text="", llm=lambda p: "x", embedder=emb)
    r = na.resolve_answer(q, bank, embedder=emb)
    assert r.needs_user and r.text == ""  # personal facts never fuzzy-guessed


def test_zero_years_experience_is_kept_not_dropped():
    bank = _bank(profile={"years_experience": 0})
    entry = next((e for e in bank if e.intent == "total_experience"), None)
    assert entry is not None and entry.text == "0"
