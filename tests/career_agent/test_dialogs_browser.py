"""The harness's dialog check on a real page: a Mercor-style referral prompt over an application form."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")

PAGE = """<html><body><h1>Welcome</h1><label>Full name <input id="name"></label>
<div role="dialog" aria-modal="true" id="ref" style="position:fixed;top:20%;left:20%;width:400px;height:240px;background:#fff">
  <button aria-label="Close" onclick="document.getElementById('ref').remove()">×</button>
  <h2>You've been referred!</h2><p>You'll be referred by Himalayas Team. You can change the code or decline.</p>
  <label>Referral code <input value="ecfe0f84"></label>
  <button onclick="document.getElementById('ref').remove(); document.body.dataset.ref='declined'">Decline</button>
  <button onclick="document.getElementById('ref').remove(); document.body.dataset.ref='yes'">Yes</button>
</div></body></html>"""


def test_the_referral_prompt_goes_to_the_agent_and_its_choice_is_pressed():
    from playwright.sync_api import sync_playwright
    from career_agent.browser import dialogs
    from career_agent.browser.page_prep import LEAVE_DIALOGS, dismiss_dialogs
    from job_dashboard.apply import session_steps as steps
    from job_dashboard.apply.session_service import ApplySession
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(PAGE)
        s = ApplySession(1, "about:blank", {}, page=page)
        token = LEAVE_DIALOGS.set(True)
        try:
            assert dismiss_dialogs(page) is False                        # the harness leaves it for the agent
        finally:
            LEAVE_DIALOGS.reset(token)
        found = steps.check_dialog(s)
        assert found["dialog"]["kind"] == "question" and found["dialog"]["buttons"] == ["Close", "Decline", "Yes"]
        with pytest.raises(steps.StepError):
            steps.press_dialog(s, "Sign up")
        steps.press_dialog(s, "Decline")
        assert page.evaluate("document.body.dataset.ref") == "declined" and dialogs.read(page) is None
        browser.close()


def test_a_field_behind_the_dialog_is_reported_and_one_inside_is_not():
    from playwright.sync_api import sync_playwright
    from job_dashboard.apply import session_steps as steps
    from job_dashboard.apply.session_service import ApplySession
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(PAGE.replace('<label>Referral code <input value="ecfe0f84">',
                                      '<label>Referral code <input id="code" value="ecfe0f84">'))
        s = ApplySession(1, "about:blank", {}, page=page)
        assert steps.behind_dialog(s, ["#name", "#code"]) == ["#name"]
        steps.press_dialog(s, "Decline")
        assert steps.behind_dialog(s, ["#name"]) == []
        browser.close()


def test_the_harness_opens_its_tab_in_the_background(tmp_path, capsys):
    from playwright.sync_api import sync_playwright
    from job_dashboard.agent_browser import background_tab
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(tmp_path / "profile"))     # the default context, as over CDP
        mine = context.pages[0] if context.pages else context.new_page()
        tab = background_tab(context)
        assert tab is not mine and tab.url == "about:blank"
        assert "background tab unavailable" not in capsys.readouterr().out
        context.close()


HEADLESS_UI = """<html><body><label>Full legal name <input id="name"></label>
<div role="dialog" aria-modal="true" id="ref" style="position:relative"><div style="position:fixed;inset:0">
  <div style="position:fixed;top:20%;left:20%;width:400px;height:240px;background:#fff">
  <h3>You've been referred!</h3><p>You'll be referred by Himalayas Team.</p>
  <button onclick="document.getElementById('ref').remove(); document.body.dataset.ref='declined'">Decline</button>
  <button>Yes</button></div></div></div></body></html>"""


def test_a_zero_size_dialog_wrapper_with_a_fixed_box_counts_as_open():
    from playwright.sync_api import sync_playwright
    from career_agent.browser import dialogs
    from job_dashboard.apply import session_steps as steps
    from job_dashboard.apply.session_service import ApplySession
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(HEADLESS_UI)
        assert page.evaluate("document.getElementById('ref').getBoundingClientRect().height") == 0
        s = ApplySession(1, "about:blank", {}, page=page)
        found = steps.check_dialog(s)
        assert found["dialog"]["kind"] == "question" and found["dialog"]["buttons"] == ["Decline", "Yes"]
        assert steps.behind_dialog(s, ["#name"]) == ["#name"]
        steps.press_dialog(s, "Decline")
        assert page.evaluate("document.body.dataset.ref") == "declined" and dialogs.read(page) is None
        browser.close()


def test_page_buttons_hidden_under_a_modal_are_not_waited_on():
    import time
    from playwright.sync_api import sync_playwright
    from career_agent.boards.drivers import _in_dialog
    chrome = "".join(f"<button>Nav {i}</button>" for i in range(10))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(f'<div aria-hidden="true">{chrome}</div>'
                         '<div role="dialog" aria-modal="true"><textarea id="note"></textarea><button>Send</button></div>')
        start = time.monotonic()
        hidden = [_in_dialog(page, f"button:Nav {i}") for i in range(10)]
        took = time.monotonic() - start
        inside = _in_dialog(page, "#note")
        browser.close()
    assert hidden == [False] * 10 and inside is True
    assert took < 2          # each lookup used to wait out a 1.5s timeout


def test_a_captcha_typed_into_a_plain_box_is_a_wall():
    from playwright.sync_api import sync_playwright
    from career_agent.orchestrator.browser_deps import BrowserDeps
    from job_dashboard.apply import session_steps as steps
    from job_dashboard.apply.session_service import ApplySession
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content('<label>Full name <input id="n"></label><img alt="captcha" src="data:,">'
                         '<label>CAPTCHA * <input id="c" maxlength="10"></label><button>Next</button>')
        out = steps.snapshot(ApplySession(1, "about:blank", {"deps": BrowserDeps()}, page=page))
        browser.close()
    assert out["blocked"] == "captcha" and "CAPTCHA" in out["detail"]
