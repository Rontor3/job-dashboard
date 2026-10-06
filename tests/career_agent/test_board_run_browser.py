"""run_board end to end on offline pages served via page.route (no real site):
submit gate, human answers, confirmation from the board's own response."""
import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")

ONE_CLICK = """<html><body><h1>Data Scientist</h1>
<button id="apply" onclick="fetch('/api/apply',{method:'POST',body:'{}'})">Apply now</button></body></html>"""

WIZARD = """<html><body><h1>Data Scientist</h1>
<button id="apply" onclick="document.getElementById('m').style.display='block'">Apply</button>
<div id="m" style="display:none">
  <label for="ctc">What is your expected CTC?</label><input id="ctc" type="text" required>
  <button onclick="fetch('/api/submit',{method:'POST',body:JSON.stringify({ctc:document.getElementById('ctc').value})})">Submit application</button>
</div></body></html>"""

GATED = """<html><body><h1>AI Engineer</h1>
<button id="apply" onclick="document.getElementById('m').style.display='block'">Apply</button>
<div id="m" style="display:none"><fieldset><legend>Where are you based?</legend>
  <label><input type="radio" name="loc" value="in" onchange="s.disabled=false">I am currently in</label>
  <label><input type="radio" name="loc" value="relocate" onchange="s.disabled=false">I can relocate to</label></fieldset>
  <button id="s" disabled onclick="fetch('/api/submit',{method:'POST',body:document.querySelector('input[name=loc]:checked').value})">Send application</button>
</div></body></html>"""

PREOPEN = WIZARD.replace('<div id="m" style="display:none">', '<div id="m" role="dialog">')

CHALLENGE = "<html><body><h2>Please verify you are human</h2><button id='apply'>Apply</button></body></html>"


def _board(submits, capture):
    return {"id": "board:test", "archetype": "form", "entry": {"selector": "#apply", "submits": submits},
            "confirm": [{"capture": capture, "status": 200}], "advance": ["Next"],
            "final": ["Submit application", "Send application"], "challenge": ["verify you are human"],
            "logged_out": [], "interstitial": []}


class Human:
    def __init__(self, ok=True, answers=None):
        self.ok, self.answers, self.cards = ok, answers or {}, []

    def approve(self, card):
        self.cards.append(card)
        return self.ok

    def collect(self, fields):
        return {f.ref: self.answers[f.label] for f in fields if f.label in self.answers}

    def get_events(self):
        return {}


def _run(html, board, human, monkeypatch, **ctx):
    from playwright.sync_api import sync_playwright
    from career_agent.boards import run as run_mod
    from career_agent.orchestrator.browser_deps import BrowserDeps
    monkeypatch.setattr(run_mod, "answer_fields", lambda fields, c: ([], list(fields)))
    hits = []

    def handle(route):
        if "/api/" in route.request.url:
            hits.append(route.request.post_data)
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))
        route.fulfill(status=200, content_type="text/html", body=html)

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.route("http://board.test/**", handle)
        page.goto("http://board.test/job")
        out = run_mod.run_board(page, board, {"deps": BrowserDeps(), "human": human, "profile": None, **ctx})
        b.close()
    return out, hits


def test_one_click_without_submit_flag_never_clicks(monkeypatch):
    out, hits = _run(ONE_CLICK, _board("yes", "/api/apply"), Human(), monkeypatch, do_submit=False)
    assert out["stopped_reason"] == "dry_run" and not out["submitted"] and hits == []


def test_one_click_approved_is_confirmed_by_board_response(monkeypatch):
    h = Human(ok=True)
    out, hits = _run(ONE_CLICK, _board("yes", "/api/apply"), h, monkeypatch, do_submit=True)
    assert out["submitted"] and out["stopped_reason"] == "submitted"
    assert len(hits) == 1 and len(h.cards) == 1


def test_one_click_declined_by_human_never_clicks(monkeypatch):
    out, hits = _run(ONE_CLICK, _board("yes", "/api/apply"), Human(ok=False), monkeypatch, do_submit=True)
    assert out["stopped_reason"] == "dry_run" and hits == []


def test_wizard_asks_human_then_submits_with_answer(monkeypatch):
    h = Human(answers={"What is your expected CTC?": "30"})
    out, hits = _run(WIZARD, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True)
    assert out["submitted"], out
    assert json.loads(hits[0]) == {"ctc": "30"}
    assert h.cards == []                      # autonomous: standing authorization, no per-app tap


def test_wizard_missing_required_answer_stops_before_submit(monkeypatch):
    out, hits = _run(WIZARD, _board("no", "/api/submit"), Human(), monkeypatch, do_submit=True, autonomous=True)
    assert out["stopped_reason"] == "needs_human" and hits == []
    assert [f["label"] for f in out["pending_human"]] == ["What is your expected CTC?"]


def test_challenge_page_stops_immediately(monkeypatch):
    out, hits = _run(CHALLENGE, _board("yes", "/api/apply"), Human(), monkeypatch, do_submit=True)
    assert out["stopped_reason"] == "challenge" and hits == []


def test_probe_one_click_proves_entry_without_clicking(monkeypatch):
    out, hits = _run(ONE_CLICK, _board("yes", "/api/apply"), Human(), monkeypatch, probe=True)
    assert out["stopped_reason"] == "probe" and hits == []


def test_probe_wizard_reports_fields_without_typing(monkeypatch):
    h = Human(answers={"What is your expected CTC?": "30"})
    out, hits = _run(WIZARD, _board("no", "/api/submit"), h, monkeypatch, probe=True, do_submit=True)
    assert out["stopped_reason"] == "probe" and hits == [] and h.cards == []
    assert [f["label"] for f in out["pending_human"]] == ["What is your expected CTC?"]


def test_optional_field_gating_a_disabled_submit_is_asked(monkeypatch):
    # Live Wellfound 2026-09-27: Send stays disabled until the (non-required)
    # location radio is answered.
    h = Human(answers={"Where are you based?": "I can relocate to"})
    out, hits = _run(GATED, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True)
    assert out["submitted"], out
    assert hits == ["relocate"]


def test_apply_modal_already_open_on_load_is_still_the_form(monkeypatch):
    # Live Wellfound 2026-09-27: the interrupted application re-opened on page
    # load, so the pre-click baseline swallowed every form field.
    h = Human(answers={"What is your expected CTC?": "30"})
    out, hits = _run(PREOPEN, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True)
    assert out["submitted"], out
    assert json.loads(hits[0]) == {"ctc": "30"}


def test_perception_refs_escape_ids_with_css_metacharacters():
    # Live Wellfound 2026-09-27: id "react-select-form-input--qualification.location.locationId-input"
    # produced ref "#…qualification.location…", which (dots = classes) matched nothing.
    from playwright.sync_api import sync_playwright
    from career_agent.orchestrator.browser_deps import BrowserDeps
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page()
        pg.set_content('<label for="a.b:c">City</label><input id="a.b:c" type="text">')
        f = next(x for x in BrowserDeps().snapshot(pg) if x.label == "City")
        assert pg.locator(f.ref).count() == 1
        b.close()


BANK = """<html><body><h1>Data Scientist</h1>
<button id="apply" onclick="document.getElementById('m').style.display='block'">Apply</button>
<div id="m" style="display:none">
  <label for="n">Full name</label><input id="n" type="text">
  <label for="b">Bank account number</label><input id="b" type="text" required>
  <button onclick="fetch('/api/submit',{method:'POST',body:'{}'})">Submit application</button>
</div></body></html>"""


def test_a_required_bank_field_stops_the_run_and_is_never_asked_or_submitted(monkeypatch):
    h = Human(answers={"Bank account number": "000111222"})
    out, hits = _run(BANK, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True)
    assert out["stopped_reason"] == "sensitive_field" and not out["submitted"] and hits == []
    assert [f["label"] for f in out["pending_human"]] == ["Bank account number"]


class FakeAssist:
    """Stands in for ClaudeAssist: on its first call it clicks `selector` and says it acted; afterwards it gives up."""
    def __init__(self, selector):
        self.selector, self.reasons = selector, []

    def recover(self, page, reason):
        self.reasons.append(reason)
        if len(self.reasons) > 1:
            return False
        page.locator(self.selector).click()
        return True


# the entry control is not the one the board profile expects (#apply is missing; this one is #start)
WRONG_ENTRY = WIZARD.replace('id="apply"', 'id="start"')

# after the answers the form shows a "Proceed" control the board's advance list does not know; it reveals the final button
HIDDEN_FINAL = WIZARD.replace(
    '<button onclick="fetch(\'/api/submit\'',
    '<button id="go" onclick="document.getElementById(\'f\').style.display=\'block\'">Proceed</button>'
    '<button id="f" style="display:none" onclick="fetch(\'/api/submit\'')


def test_no_entry_is_recovered_by_assist_and_the_run_continues(monkeypatch):
    h = Human(answers={"What is your expected CTC?": "30"})
    assist = FakeAssist("#start")
    out, hits = _run(WRONG_ENTRY, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True,
                     assist=assist)
    assert assist.reasons == ["no_entry"] and out["submitted"], out


def test_without_assist_a_missing_entry_still_stops_as_no_entry(monkeypatch):
    out, hits = _run(WRONG_ENTRY, _board("no", "/api/submit"), Human(), monkeypatch, do_submit=True, autonomous=True)
    assert out["stopped_reason"] == "no_entry" and hits == []


def test_no_advance_control_is_recovered_by_assist(monkeypatch):
    h = Human(answers={"What is your expected CTC?": "30"})
    assist = FakeAssist("#go")
    out, hits = _run(HIDDEN_FINAL, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True,
                     assist=assist)
    assert assist.reasons == ["no_advance_control"] and out["submitted"], out
    assert json.loads(hits[0]) == {"ctc": "30"}


def test_when_assist_gives_up_the_run_stops_as_before(monkeypatch):
    h = Human(answers={"What is your expected CTC?": "30"})
    assist = FakeAssist("#go")
    assist.reasons = ["already used"]                       # a second call returns False
    out, hits = _run(HIDDEN_FINAL, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True,
                     assist=assist)
    assert not out["submitted"] and hits == []


# the SuccessFactors-style login page seen live (inputs are NOT html-required; labels carry the asterisk)
LOGIN_PAGE = """<html><body><h1>Sign in</h1>
<label for="u">Email Address:*</label><input id="u" name="username" type="text">
<label for="p">Password:*</label><input id="p" name="password" type="password">
<button type="submit">Sign In</button> <a href="#">Forgot your password?</a> <a href="#">Create an account</a>
</body></html>"""
OFF_BOARD_ENTRY = """<html><body><h1>Data Scientist</h1>
<a id="apply" href="http://company.test/careers/apply">Apply on company site</a></body></html>"""


def _run_two_hosts(html_board, html_other, board, human, monkeypatch, **ctx):
    from playwright.sync_api import sync_playwright
    from career_agent.boards import run as run_mod
    from career_agent.orchestrator.browser_deps import BrowserDeps
    monkeypatch.setattr(run_mod, "answer_fields", lambda fields, c: ([], list(fields)))
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.route("http://board.test/**", lambda r: r.fulfill(status=200, content_type="text/html", body=html_board))
        page.route("http://company.test/**", lambda r: r.fulfill(status=200, content_type="text/html", body=html_other))
        page.goto("http://board.test/job")
        out = run_mod.run_board(page, board, {"deps": BrowserDeps(), "human": human, "profile": None, **ctx})
        b.close()
    return out


def test_a_flow_that_leaves_the_board_stops_as_left_board_for_the_other_engine(monkeypatch):
    board = {**_board("no", "/api/submit"), "domains": ["board.test"]}
    h = Human()
    out = _run_two_hosts(OFF_BOARD_ENTRY, LOGIN_PAGE, board, h, monkeypatch, do_submit=True, autonomous=True)
    assert out["stopped_reason"] == "left_board" and out["url"].startswith("http://company.test/"), out
    assert h.cards == [] and out["pending_human"] == []                    # nothing was asked of the human


LOGIN_AFTER_APPLY = ('<html><body><h1>Data Scientist</h1><button id="apply" onclick="document.getElementById(\'m\').style.display=\'block\'">'
                     'Apply</button><div id="m" style="display:none">' + LOGIN_PAGE.split("<body>")[1].replace("</body></html>", "") + "</div></body></html>")


def test_a_login_page_is_never_turned_into_questions(monkeypatch):
    h = Human()
    out, hits = _run(LOGIN_AFTER_APPLY, _board("no", "/api/submit"), h, monkeypatch, do_submit=True, autonomous=True)
    assert h.cards == []
    assert out["stopped_reason"] == "auth_wall" and out["pending_human"] == [] and hits == []
