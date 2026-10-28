from career_agent.memory.qbank_match import generic_company


def test_the_employer_name_reads_as_this_company():
    assert generic_company("How did you hear about Twilio?", {"company": "Twilio Inc."}) == "How did you hear about this company?"
    assert generic_company("Have you worked at Amgen before?", {"company": "Amgen Technology Private Limited"}) == \
        "Have you worked at this company before?"


def test_no_company_or_unrelated_text_is_untouched():
    assert generic_company("Your notice period?", {"company": "Twilio"}) == "Your notice period?"
    assert generic_company("How did you hear about us?", None) == "How did you hear about us?"
