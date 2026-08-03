from job_dashboard.classify import company as cc


def test_dictionary_hit_exact(tmp_path):
    ind, typ, method = cc.classify_company("Accenture Solutions Pvt Ltd", llm=lambda p: "unused")
    assert ind == "Consulting & IT Services" and typ == "Services/Consultancy" and method == "dict"


def test_llm_fallback_parses_vocab(tmp_path):
    def fake(prompt):
        return "Industry: Fintech\nCompany-type: Startup"
    ind, typ, method = cc.classify_company("Zibbra Pay", llm=fake)
    assert ind == "Fintech" and typ == "Startup" and method == "llm"


def test_llm_offvocab_coerced_to_other():
    def fake(prompt):
        return "Industry: Croquet\nCompany-type: Wizardry"
    ind, typ, method = cc.classify_company("Weird Co", llm=fake)
    assert ind == "Other" and typ == "Other" and method == "llm"


def test_llm_raise_is_caught_returns_other():
    def boom(prompt):
        raise RuntimeError("ollama down")
    ind, typ, method = cc.classify_company("Anything", llm=boom)
    assert (ind, typ, method) == ("Other", "Other", "other")


def test_longer_dict_key_wins_over_short_substring():
    # "ust" must not hijack a company that merely contains it; longer keys first.
    ind, typ, _ = cc.classify_company("Thermo Fisher Scientific", llm=lambda p: "x")
    assert ind == "Life Sciences & Scientific"
