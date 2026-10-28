"""A date box holding 'MM/DD/YYYY' is the site's placeholder, not an answer.

ICF (live 2026-10-27): the From*/To* boxes carried the site's own tokens, has_value
called them filled, the run dropped the questions, and the résumé-derived entry
dates were never written."""
from src.career_agent.browser.date_widgets import plausible_date_text


def test_real_dates():
    assert plausible_date_text("15/03/1998")
    assert plausible_date_text("1998-03-15")
    assert plausible_date_text("4 Nov 2026")
    assert plausible_date_text("07/2023")            # month-year: the entry-date shape
    assert plausible_date_text("Jul 2023")
    assert plausible_date_text("7-2023")


def test_placeholders_and_junk():
    assert not plausible_date_text("MM/DD/YYYY")
    assert not plausible_date_text("dd-mm-yyyy")
    assert not plausible_date_text("____-__-__")
    assert not plausible_date_text("From")
    assert not plausible_date_text("TBD")
    assert not plausible_date_text("")
    assert not plausible_date_text(None)
    # a real date never collides with the mask guard
    assert plausible_date_text("03/15/1998")
