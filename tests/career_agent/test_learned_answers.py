import sqlite3

from career_agent.browser.form_model import Field
from career_agent.memory.learned_answers import AnswerMemory, ensure


def _f(ref, label, kind="text", purpose=None):
    return Field(ref, kind, label, False, [], None, purpose)


def _mem():
    conn = sqlite3.connect(":memory:")
    ensure(conn)
    return AnswerMemory(conn)


def test_exact_recall_after_record():
    m = _mem()
    m.record(_f("#np", "Notice period (in days)"), "30")
    decisions, still = m.recall([_f("#np2", "Notice Period (in days)")])   # case/space variance
    assert not still
    assert decisions[0].value == "30" and decisions[0].action == "fill"
    assert decisions[0].source == "learned"


def test_purpose_recall_across_wording():
    m = _mem()
    m.record(_f("#a", "Total years of experience?", purpose="years_experience"), "5")
    # different wording, same purpose -> reused
    decisions, still = m.recall([_f("#b", "How many years have you worked?", purpose="years_experience")])
    assert not still and decisions[0].value == "5"


def test_fts_fuzzy_recall_on_shared_tokens():
    m = _mem()
    m.record(_f("#s", "Expected salary in USD"), "120000")
    decisions, still = m.recall([_f("#s2", "What is your expected salary (USD)?")])
    assert not still and decisions[0].value == "120000"


def test_unrelated_question_escalates():
    m = _mem()
    m.record(_f("#s", "Expected salary in USD"), "120000")
    fields = [_f("#x", "Do you have a valid passport?")]
    decisions, still = m.recall(fields)
    assert decisions == [] and [f.ref for f in still] == ["#x"]


def test_textarea_never_recorded_or_recalled():
    m = _mem()
    m.record(_f("#w", "Why do you want to work at Acme?", kind="textarea"), "I love Acme.")
    decisions, still = m.recall([_f("#w2", "Why do you want to work at Acme?", kind="textarea")])
    assert decisions == [] and [f.ref for f in still] == ["#w2"]


def test_record_updates_existing_answer():
    m = _mem()
    m.record(_f("#np", "Notice period"), "60")
    m.record(_f("#np", "Notice period"), "30")   # changed answer overwrites
    decisions, _ = m.recall([_f("#np", "Notice period")])
    assert decisions[0].value == "30"


def test_record_corrections_diffs_and_learns():
    from career_agent.orchestrator.mapper import FillDecision
    m = _mem()
    form = [_f("#p", "Phone", purpose="phone"), _f("#np", "Notice period")]
    decisions = [FillDecision("#p", "text", "Phone", "+91 000", "fill", "resume"),
                 FillDecision("#np", "text", "Notice period", "30 days", "fill", "learned")]
    final = {"#p": "+91 99999", "#np": "30 days"}      # phone changed by human, notice unchanged
    m.record_corrections(form, decisions, final)
    # the changed one is learned; recall now returns the corrected value
    dec, still = m.recall([_f("#p2", "Phone", purpose="phone")])
    assert dec and dec[0].value == "+91 99999"
    # the unchanged one was NOT recorded (nothing to learn) -> not recalled
    dec2, still2 = m.recall([_f("#np2", "Notice period")])
    assert dec2 == [] and "#np2" in {f.ref for f in still2}
