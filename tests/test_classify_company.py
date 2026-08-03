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


def test_dict_hit_on_compound_name_prefix():
    # "jpmorgan" prefix must still hit inside "JPMorganChase".
    ind, typ, method = cc.classify_company("JPMorganChase", llm=lambda p: "x")
    assert ind == "BFSI" and method == "dict"


def test_short_key_no_midword_false_hit():
    # "ust"/"exl" must NOT match inside unrelated names — those fall through to LLM.
    ind, _, method = cc.classify_company(
        "Reliance Industries Ltd",
        llm=lambda p: "Industry: Energy & Utilities\nCompany-type: Product")
    assert method == "llm" and ind == "Energy & Utilities"  # not dict-matched via "ust"
    # but the real company UST still hits the dictionary
    ind2, _, m2 = cc.classify_company("UST Global", llm=lambda p: "x")
    assert m2 == "dict" and ind2 == "Consulting & IT Services"


def test_non_string_company_never_raises():
    ind, typ, method = cc.classify_company(
        float("nan"), llm=lambda p: "Industry: BFSI\nCompany-type: Product")
    assert isinstance(ind, str) and isinstance(typ, str) and isinstance(method, str)
    assert cc.classify_company(None) == ("Other", "Other", "other")
