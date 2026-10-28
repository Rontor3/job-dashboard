"""Every field knows the heading it sits under and which repeated entry block it is in."""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")


def test_section_and_row_come_from_the_page_structure():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import collect_raw, to_form_model
    url = (Path(__file__).parent / "fixtures" / "sectioned_form.html").resolve().as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.goto(url)
        fields = to_form_model(collect_raw(pg))
        b.close()
    by = {}
    for f in fields:
        by.setdefault(f.label.strip(" *"), []).append(f)
    assert by["First Name"][0].section == "Contact Information" and by["First Name"][0].row == -1
    assert [f.section for f in by["Degree"]] == ["Education"] * 3
    assert [f.row for f in by["School"]] == [0, 1, 2]                       # three entries
    spons = next(f for f in fields if f.kind == "radio_group")
    assert spons.section == "Work authorization"                             # a fieldset legend
    assert by["Current job title"][0].section == "Experience"
