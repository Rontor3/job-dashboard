from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Experience, Education
from career_agent.orchestrator.judgment import (
    JudgmentContext, profile_to_text, _is_sensitive, map_option, judge,
    _looks_like_question, judge_combobox_value, cover_note_question, COVER_NOTE_ASK,
)


def _f(ref, label, purpose=None, kind="text", options=None, required=False):
    return Field(ref, kind, label, required, options or [], None, purpose)


def test_profile_to_text_includes_experience_and_skills():
    p = CandidateProfile(
        contact={"full_name": "Rakshit Singh"},
        experiences=[Experience("Tata AIG", "Data Scientist", "2023", "Present", ["Built fraud models"])],
        education=[Education("IIT BHU", "B.Tech", "Ceramics")],
        skills=["Python", "SQL"])
    t = profile_to_text(p)
    assert "Rakshit Singh" in t and "Tata AIG" in t and "Data Scientist" in t
    assert "Built fraud models" in t and "Python" in t and "B.Tech" in t


def test_is_sensitive_flags_demographics_and_attestation():
    assert _is_sensitive(_f("#g", "Gender"))
    assert _is_sensitive(_f("#e", "Are you Hispanic/Latino?"))
    assert _is_sensitive(_f("#v", "Have you served in the armed forces?", purpose="veteran"))
    assert _is_sensitive(_f("#d", "Disability status"))
    assert _is_sensitive(_f("#a", "I certify this is true", purpose="attestation"))
    assert not _is_sensitive(_f("#q", "Why do you want this role?", kind="textarea"))
    assert _is_sensitive(_f("#age", "Please select your age category:"))
    assert _is_sensitive(_f("#dob", "Date of Birth"))


def test_judge_combobox_value_returns_short_llm_reply():
    llm = lambda prompt: "Yes"
    assert judge_combobox_value("Are you legally authorized to work in India?", "x", llm) == "Yes"


def test_judge_combobox_value_none_on_llm_failure():
    def boom(prompt): raise RuntimeError("down")
    assert judge_combobox_value("Some question", "x", boom) is None


def test_judge_fills_combobox_with_no_known_options_via_short_answer():
    # Workday-style dropdown-button: kind=combobox but options are unknown
    # until the browser opens it — judge() must draft a short answer for the
    # filler to later match against the real live options, not escalate blindly.
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#cb", "Are you legally authorized to work in India?", kind="combobox", required=True)
    llm = lambda prompt: "Yes"
    answered, still_need, flagged = judge([q], ctx, llm)
    d = {x.ref: x for x in answered}
    assert d["#cb"].value == "Yes" and d["#cb"].action == "combobox"
    assert still_need == []


def test_judge_age_category_combobox_escalates_never_guessed():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#age", "Please select your age category:", kind="combobox", required=True)
    called = {"n": 0}
    def llm(prompt): called["n"] += 1; return "18-24"
    answered, still_need, flagged = judge([q], ctx, llm)
    assert "#age" in {f.ref for f in still_need}
    assert answered == [] and called["n"] == 0


def test_map_option_picks_a_real_option_or_none():
    opts = ["High school", "Bachelor's degree", "Master's degree"]
    llm_ok = lambda prompt: "Bachelor's degree"
    assert map_option("Highest level of education", opts, "B.Tech from IIT", llm_ok) == "Bachelor's degree"
    llm_bad = lambda prompt: "PhD"
    assert map_option("Highest level of education", opts, "B.Tech", llm_bad) is None
    llm_none = lambda prompt: "NONE"
    assert map_option("Highest level of education", opts, "B.Tech", llm_none) is None
    # LLM wraps the choice in a sentence -> accept the single contained option
    llm_verbose = lambda prompt: "The candidate holds a Bachelor's degree (B.Tech)."
    assert map_option("Highest level of education", opts, "B.Tech", llm_verbose) == "Bachelor's degree"
    # reply mentions two options -> ambiguous -> escalate
    llm_ambig = lambda prompt: "Between Bachelor's degree and Master's degree, likely the former."
    assert map_option("Highest level of education", opts, "B.Tech", llm_ambig) is None


def test_judge_answers_freetext_flags_and_escalates_sensitive():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme", "description": "..."},
                          profile_text="Rakshit, Data Scientist at Tata AIG")
    freetext = _f("#q", "What interests you about this role?", kind="text", required=True)
    gender = _f("#g", "Gender", kind="text")
    llm = lambda prompt: "I'm excited about Acme because of my ML work at Tata AIG."
    answered, still_need, flagged = judge([freetext, gender], ctx, llm, cap=6)
    d = {x.ref: x for x in answered}
    assert d["#q"].source == "judgment" and "Acme" in d["#q"].value
    assert "#g" in {f.ref for f in still_need}          # sensitive -> escalate
    assert "#q" not in {f.ref for f in still_need}


def test_judge_never_answers_a_search_box():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    search = _f("#s", "Search", kind="text")
    called = {"n": 0}
    def llm(prompt): called["n"] += 1; return "some answer"
    answered, still_need, flagged = judge([search], ctx, llm)
    assert "#s" in {f.ref for f in still_need}     # escalated, not answered
    assert called["n"] == 0                        # llm never called for a search box


def test_judge_maps_enum_or_escalates():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="B.Tech IIT")
    edu = _f("#edu", "Highest level of education", kind="select",
             options=["Bachelor's degree", "Master's degree"], required=True)
    llm = lambda prompt: "Bachelor's degree"
    answered, still_need, flagged = judge([edu], ctx, llm)
    assert {x.ref: x for x in answered}["#edu"].value == "Bachelor's degree"


def test_judge_respects_cap():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q1 = _f("#q1", "One-word motivation?", kind="text", required=True)
    q2 = _f("#q2", "Another short answer?", kind="text", required=True)
    llm = lambda prompt: "grounded answer"
    answered, still_need, flagged = judge([q1, q2], ctx, llm, cap=1)
    assert len(answered) == 1 and len(still_need) == 1   # cap hit -> one escalates


def test_judge_never_raises_on_llm_failure():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#q", "Short answer?", kind="text", required=True)
    def boom(prompt): raise RuntimeError("ollama down")
    answered, still_need, flagged = judge([q], ctx, boom, cap=6)
    assert "#q" in ({x.ref for x in answered} | {f.ref for f in still_need})


def test_looks_like_question():
    assert _looks_like_question("Why do you want to work here?")
    assert _looks_like_question("Tell us about a challenge you faced")  # no "?", 4+ words
    assert not _looks_like_question("India")
    assert not _looks_like_question("Select One")
    assert not _looks_like_question("Postal Code")
    assert not _looks_like_question("")


def test_judge_never_essay_drafts_a_mislabeled_dropdown():
    # Mis-perceived dropdowns surface their current value ("India") or
    # placeholder ("Select One") as the label — must escalate, never essay-draft.
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    bogus = _f("#f3", "India", kind="text", required=True)
    called = {"n": 0}
    def llm(prompt): called["n"] += 1; return "a fabricated cover letter paragraph"
    answered, still_need, flagged = judge([bogus], ctx, llm)
    assert "#f3" in {f.ref for f in still_need}
    assert "#f3" not in {x.ref for x in answered}
    assert called["n"] == 0


def test_judge_never_essay_drafts_a_classified_short_field():
    # A field with a real purpose (postal_code, phone, etc.) must never be
    # handed to the essay drafter — draft_screening_answer writes prose, which
    # is wrong for a structured short-answer field. It should escalate instead.
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    postal = _f("#zip", "Postal Code", kind="text", purpose="postal_code", required=True)
    called = {"n": 0}
    def llm(prompt): called["n"] += 1; return "prose that should never land here"
    answered, still_need, flagged = judge([postal], ctx, llm)
    assert "#zip" in {f.ref for f in still_need}
    assert "#zip" not in {x.ref for x in answered}
    assert called["n"] == 0


def test_judge_tier3_orchestrator_answers_weak_freetext():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#q", "Short answer?", kind="text", required=True)
    def boom(prompt): raise RuntimeError("ollama down")   # -> general_fallback (weak)
    orch = lambda items: {it["ref"]: "Orchestrator-drafted answer." for it in items}
    answered, still_need, flagged = judge([q], ctx, boom, cap=6, orchestrator=orch)
    d = {x.ref: x for x in answered}
    assert d["#q"].source == "orchestrator" and "Orchestrator" in d["#q"].value


def _conf_llm(conf):
    return lambda p: '{"answer": "Because fraud ML.", "confidence": %s, "basis": "x"}' % conf


def test_judge_low_confidence_is_not_filled_but_recorded():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#q", "What interests you about this role?", kind="text", required=True)
    seen = []
    answered, still_need, _ = judge([q], ctx, _conf_llm(30), min_conf=60,
                                    on_draft=lambda f, res, filled: seen.append((f.ref, res["confidence"], filled)))
    assert answered == [] and [f.ref for f in still_need] == ["#q"]
    assert seen == [("#q", 30, False)]


def test_judge_confident_answer_fills_and_unknown_confidence_does_not():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#q", "What interests you about this role?", kind="text", required=True)
    ok, need, _ = judge([q], ctx, _conf_llm(80), min_conf=60)
    assert [d.ref for d in ok] == ["#q"] and need == []
    ok, need, _ = judge([q], ctx, lambda p: "plain prose", min_conf=60)   # unknown -> untrusted
    assert ok == [] and [f.ref for f in need] == ["#q"]
    ok, _, _ = judge([q], ctx, lambda p: "plain prose")                    # gate off -> as before
    assert [d.ref for d in ok] == ["#q"]


def test_judge_drafts_prose_purposes_the_profile_cannot_fill():
    # Live Work at a Startup 2026-09-27: the founder-message box was classified
    # (motivation/summary) and so never reached the drafter.
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    msg = _f("#m", "Start a conversation with the team at Acme. Why does Acme interest you?",
             kind="textarea", purpose="motivation", required=False)
    answered, still_need, _ = judge([msg], ctx, _conf_llm(90), min_conf=60)
    assert [x.ref for x in answered] == ["#m"] and answered[0].source == "judgment"


def test_judge_forwards_story_text(monkeypatch):
    from career_agent.orchestrator import judgment
    seen = {}

    def fake_draft(job, q, profile_text, research, resume_text, llm=None, story_text=""):
        seen["story"] = story_text
        return {"answer": "x", "confidence": 90, "basis": "", "prompt": "", "flags": [],
                "unsupported_company_claims": []}
    monkeypatch.setattr(judgment, "draft_screening_answer", fake_draft)
    ctx = JudgmentContext(job={"title": "t", "company": "c", "description": ""},
                          story_text="Q: a\nA: b")
    f = Field("#m", "textarea", "Why do you want to join us?", True, [], None, None)
    judge([f], ctx, llm=lambda p: "")
    assert seen["story"] == "Q: a\nA: b"


def test_judge_never_fills_canned_fallback_answer():
    from career_agent.orchestrator import judgment as J
    f = Field("#q", "textarea", "What interests you about working for this company?", True, [], None, None)
    orig = J.draft_screening_answer
    J.draft_screening_answer = lambda *a, **k: {"answer": "canned", "flags": ["general_fallback"], "confidence": None}
    try:
        ctx = J.JudgmentContext(job={}, profile_text="x", resume_text="")
        answered, still, _ = J.judge([f], ctx, lambda p: "")
    finally:
        J.draft_screening_answer = orig
    assert not answered and still == [f]


def test_cover_note_question_matches_generic_free_text_boxes_only():
    for label in ("Message", "Your message", "Comments", "Additional information", "Cover letter*",
                  "Anything else you would like us to know", "Additional comments:"):
        assert cover_note_question(label) == COVER_NOTE_ASK, label
    assert cover_note_question("Why do you want to work here?") is None
    assert cover_note_question("Postal Code") is None


def test_judge_writes_a_bare_message_box_as_a_cover_note():
    # Live insyncanalytics.com/apply-now and infoveritech.com/careers: the required "Message" textarea was
    # escalated (one word, no "?") and the run waited on Telegram forever. It is now the cover-note ask.
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme", "description": "..."}, profile_text="x")
    msg = _f("#msg", "Message", kind="textarea", required=True)
    asked = []
    def longform(question, field, job):
        asked.append(question)
        return {"answer": "Short cover note.", "confidence": 90, "flags": [], "unsupported_company_claims": []}
    answered, still_need, _ = judge([msg], JudgmentContext(job=ctx.job, profile_text="x", longform=longform),
                                    lambda p: "")
    assert asked == [COVER_NOTE_ASK]
    assert [x.ref for x in answered] == ["#msg"] and answered[0].value == "Short cover note."
    assert still_need == []


def test_judge_falls_back_to_the_drafter_with_the_cover_note_ask(monkeypatch):
    from career_agent.orchestrator import judgment
    seen = {}
    def fake_draft(job, q, profile_text, research, resume_text, llm=None, story_text=""):
        seen["q"] = q
        return {"answer": "Short cover note.", "confidence": 90, "basis": "", "prompt": "", "flags": [],
                "unsupported_company_claims": []}
    monkeypatch.setattr(judgment, "draft_screening_answer", fake_draft)
    ctx = JudgmentContext(job={"title": "t", "company": "c", "description": ""})
    answered, still_need, _ = judge([_f("#c", "Comments", kind="textarea", required=True)], ctx, lambda p: "")
    assert seen["q"] == COVER_NOTE_ASK
    assert [x.ref for x in answered] == ["#c"] and still_need == []



# ── the assist child's own failure text is never an answer ──
# Live workatastartup 2026-10-20 (build acf4591f): the Claude CLI hit its weekly
# limit and the notice ITSELF was drafted into the live founder-message box
# (source 'judgment'). Error-shaped drafts must leave the field open instead.

LIMIT_NOTICE = "You've hit your weekly limit · resets Oct 22 at 5:30am (Asia/Calcutta)"


def test_error_shaped_flags_limit_notices_empties_and_stderr_echoes_only(monkeypatch):
    import career_agent.orchestrator.claude_assist as ca
    # the notice shapes
    assert ca.error_shaped(LIMIT_NOTICE)
    assert ca.error_shaped("You've used your usage limit. Your limit will reset at 2am UTC.")
    assert ca.error_shaped("error: authentication failed")
    assert ca.error_shaped("Service unavailable, try again later")
    # empty / whitespace
    assert ca.error_shaped("") and ca.error_shaped("   ") and ca.error_shaped(None)
    # verbatim echo of the child's last stderr line
    monkeypatch.setattr(ca, "_LAST_STDERR", "connect ECONNREFUSED api.anthropic.com")
    assert ca.error_shaped("connect ECONNREFUSED api.anthropic.com")
    # plausible answers are never touched — not even ones that mention rate limits
    assert not ca.error_shaped("I have shipped ML products for five years and led data teams.")
    assert not ca.error_shaped("I debugged a tricky rate limit issue at work last year.")


def test_judge_never_adopts_an_error_shaped_draft(capsys):
    # the live run's exact shape: min_conf off, the llm reply IS the limit notice
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    msg = _f("#m", "Start a conversation with the team at Acme. Why does Acme interest you?",
             kind="textarea", purpose="motivation")
    answered, still_need, flagged = judge([msg], ctx, lambda p: LIMIT_NOTICE)
    assert answered == [] and flagged == set()
    assert "#m" in {f.ref for f in still_need}          # the field stays open for the human/park
    assert "rejected error-shaped draft" in capsys.readouterr().out


def test_judge_combobox_rejects_an_error_shaped_value():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#cb", "Are you legally authorized to work in India?", kind="combobox", required=True)
    answered, still_need, _ = judge([q], ctx, lambda p: LIMIT_NOTICE)
    assert answered == [] and "#cb" in {f.ref for f in still_need}


def test_judge_still_adopts_a_plausible_draft():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    msg = _f("#m", "Start a conversation with the team at Acme. Why does Acme interest you?",
             kind="textarea", purpose="motivation")
    llm = lambda p: "I have led data science teams for five years and love shipping ML products."
    answered, still_need, _ = judge([msg], ctx, llm)
    assert [x.ref for x in answered] == ["#m"] and answered[0].source == "judgment"
    assert still_need == []
