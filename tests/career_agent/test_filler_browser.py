import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def _fixture_url():
    return (Path(__file__).parent / "fixtures" / "sample_form.html").resolve().as_uri()


def test_fill_then_readback_matches():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions, read_back
    from career_agent.orchestrator.mapper import FillDecision

    decisions = [
        FillDecision("#name", "text", "Full name", "Jane Q", "fill", "profile"),
        FillDecision("#email", "email", "Email", "jane@example.com", "fill", "profile"),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        apply_decisions(page, decisions)
        values = read_back(page, decisions)
        browser.close()

    assert values["#name"] == "Jane Q"
    assert values["#email"] == "jane@example.com"


TYPE_TO_OPEN = """<label>Country <input id=co role=combobox aria-autocomplete=list></label>
<ul role=listbox hidden><li role=option>India</li><li role=option>Indonesia</li></ul>
<script>
const box = document.getElementById('co'), list = document.querySelector('ul');
box.addEventListener('input', () => { list.hidden = false; });
list.querySelectorAll('li').forEach(li => li.onclick = () => { box.value = li.textContent; list.hidden = true; });
</script>"""


def test_a_combobox_whose_list_opens_on_typing_is_typed_into_not_clicked_while_hidden():
    import time
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions
    from career_agent.orchestrator.mapper import FillDecision

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(TYPE_TO_OPEN)
        start = time.monotonic()
        apply_decisions(page, [FillDecision("#co", "combobox", "Country", "India", "combobox", "profile")])
        took = time.monotonic() - start
        value = page.input_value("#co")
        browser.close()

    assert value == "India"
    assert took < 4          # a click on the hidden option would wait out a 4s timeout


def _yes_no(i, q):
    opt = lambda o: (f'<div><div><input id="r{i}{o}" aria-label=" {q} " type="radio" name="g{i}">'
                     f'<label for="r{i}{o}"></label></div><div><p>{o}</p></div></div>')
    return f'<fieldset role="radiogroup">{opt("Yes")}{opt("No")}</fieldset>'


LINKEDIN_RADIOS = _yes_no(1, "Do you have GenAI experience?") + _yes_no(2, "Have you used WhatsApp APIs?") \
    + _yes_no(3, "Have you built chatbots?")


def test_yes_no_questions_are_perceived_with_their_options_and_each_answer_lands_in_its_own_group():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.filler import apply_decisions
    from career_agent.browser.perception import snapshot_form
    from career_agent.orchestrator.mapper import FillDecision

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(LINKEDIN_RADIOS)
        groups = [f for f in snapshot_form(page, scroll=False, shot=False) if f.kind == "radio_group"]
        answers = dict(zip([g.ref for g in groups], ["Yes", "No", "Yes"]))
        apply_decisions(page, [FillDecision(ref, "radio_group", "", v, "check_group", "t") for ref, v in answers.items()])
        ticked = page.evaluate("[...document.querySelectorAll('input:checked')].map(e => e.id)")
        browser.close()

    assert [(g.label, g.options) for g in groups] == [("Do you have GenAI experience?", ["Yes", "No"]),
                                                      ("Have you used WhatsApp APIs?", ["Yes", "No"]),
                                                      ("Have you built chatbots?", ["Yes", "No"])]
    assert ticked == ["r1Yes", "r2No", "r3Yes"]
