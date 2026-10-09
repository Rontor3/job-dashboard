import os
from datetime import date

import pytest

from career_agent.browser.date_widgets import _option_for, parse_date_value

browser = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1")


@pytest.fixture(scope="module")
def chromium():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(chromium, monkeypatch):
    from career_agent.browser import clicks
    monkeypatch.setattr(clicks, "TIMING_SCALE", 0.01)
    pg = chromium.new_page()
    yield pg
    pg.close()


def test_parse_date_value_iso_dayfirst_and_words():
    assert parse_date_value("2026-11-04") == date(2026, 11, 4)
    assert parse_date_value("04/11/2026") == date(2026, 11, 4)          # day first: an Indian profile
    assert parse_date_value("17-03-2001") == date(2001, 3, 17)
    assert parse_date_value("4 Nov 2026") == date(2026, 11, 4) and parse_date_value("November 4, 2026") == date(2026, 11, 4)
    assert parse_date_value("30 days") is None and parse_date_value("") is None


def test_option_for_reads_day_month_year_options_however_written():
    d = date(2026, 11, 4)
    assert _option_for("day", d, ["Day", "03", "04", "05"]) == "04"
    assert _option_for("month", d, ["Month", "October", "November"]) == "November"
    assert _option_for("month", d, ["11 - Nov", "12 - Dec"]) == "11 - Nov" and _option_for("month", d, ["Jan", "Nov"]) == "Nov"
    assert _option_for("year", d, ["2025", "2026"]) == "2026" and _option_for("year", d, ["Select", "2027"]) is None


def _calendar(labelled=True):
    cell = ("b.setAttribute('aria-label','Choose '+['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']"
            "[new Date(y,m,d).getDay()]+', '+M[m]+' '+d+'th, '+y);") if labelled else ""
    return """
<label>Joining date <input id=dp readonly class=date-input placeholder='Select date'></label>
<div id=cal style='display:none'><button aria-label='Previous month' id=prev>&lt;</button><span id=title></span>
<button aria-label='Next month' id=next>&gt;</button><div id=days></div></div>
<script>
const M=['January','February','March','April','May','June','July','August','September','October','November','December'];
let y=2026,m=9; const dp=document.getElementById('dp'),cal=document.getElementById('cal');
function render(){document.getElementById('title').textContent=M[m]+' '+y;const days=document.getElementById('days');days.innerHTML='';
 for(let d=1;d<=new Date(y,m+1,0).getDate();d++){const b=document.createElement('button');b.textContent=d;""" + cell + """
  b.onclick=()=>{dp.value=String(d).padStart(2,'0')+'/'+String(m+1).padStart(2,'0')+'/'+y;cal.style.display='none'};days.append(b)}}
dp.onclick=()=>{cal.style.display='block';render()};
document.getElementById('next').onclick=()=>{m++;if(m>11){m=0;y++}render()};
document.getElementById('prev').onclick=()=>{m--;if(m<0){m=11;y--}render()};
</script>"""


@browser
@pytest.mark.parametrize("labelled", [True, False])
@pytest.mark.parametrize("target,expect", [(date(2026, 11, 4), "04/11/2026"), (date(2026, 8, 15), "15/08/2026"),
                                           (date(2026, 10, 20), "20/10/2026"), (date(2027, 2, 9), "09/02/2027")])
def test_calendar_popup_is_navigated_to_the_day(page, labelled, target, expect):
    from career_agent.browser.date_widgets import pick_calendar
    page.set_content(_calendar(labelled))
    assert pick_calendar(page, page, "#dp", target)
    assert page.input_value("#dp") == expect


PARTS = """
<fieldset><legend>Date of joining *</legend>
<select id=d><option>Day</option>""" + "".join(f"<option>{i:02d}</option>" for i in range(1, 32)) + """</select>
<select id=m><option>Month</option>""" + "".join(f"<option>{n}</option>" for n in ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]) + """</select>
<input id=y placeholder=YYYY></fieldset>"""


@browser
def test_day_month_year_boxes_become_one_date_field_and_are_filled(page):
    from career_agent.browser.filler import apply_decisions
    from career_agent.browser.perception import snapshot_form
    from career_agent.orchestrator.mapper import FillDecision, _action_for_kind
    page.set_content(PARTS)
    fields = snapshot_form(page)
    (f,) = [x for x in fields if x.kind == "date_parts"]
    assert f.label.startswith("Date of joining") and f.required and len(fields) == 1
    apply_decisions(page, [FillDecision(f.ref, f.kind, f.label, "2026-11-04", _action_for_kind(f.kind), "t")])
    assert page.eval_on_selector("#d", "e => e.value") == "04" and page.eval_on_selector("#m", "e => e.value") == "November"
    assert page.input_value("#y") == "2026"


@browser
def test_readonly_calendar_box_is_perceived_and_filled_through_the_normal_path(page):
    from career_agent.browser.filler import apply_decisions
    from career_agent.browser.perception import snapshot_form
    from career_agent.orchestrator.mapper import FillDecision, _action_for_kind
    page.set_content(_calendar())
    (f,) = [x for x in snapshot_form(page) if x.kind == "datepicker"]
    apply_decisions(page, [FillDecision(f.ref, f.kind, f.label, "2026-12-25", _action_for_kind(f.kind), "t")])
    assert page.input_value("#dp") == "25/12/2026"
