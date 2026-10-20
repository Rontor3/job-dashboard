"""Fill-probe mode, offline (no Playwright, no browser): when a dry-run boards run hits
the irreversible-entry guard with a fillable flow behind that entry, it must fill everything
reversible, refuse the final commit and stop `reached_submit_dry_run` with the fills counted
(live 2026-10-20: naukri, instahyre, iimjobs, wellfound, workatastartup all died `dry_run`,
filled=0, the flow never ran). Authorized runs and probe mode must stay byte-identical.

Fakes model the page/deps/capture contract run_board touches: one screen at a time, a
naukri chat whose bubbles advance per sent answer, canned board responses; run_mod seams
are monkeypatched the same way test_board_run_browser._run patches its internals."""
import json

from career_agent.browser.form_model import Field
from career_agent.boards.drivers import FormDriver
from career_agent.orchestrator.mapper import FillDecision

Q1 = "Are you currently residing in Gurugram or willing to relocate to Gurugram?"
Q2 = "What is your notice period?"

_QN = [{"questionId": "1", "questionName": Q1, "questionType": "Radio Button",
        "isMandatory": True, "answerOption": {"1": "Yes", "2": "No"}, "prefillData": ["Yes"]},
       {"questionId": "2", "questionName": Q2, "questionType": "Text Box",
        "isMandatory": True, "prefillData": ["2 Months"]}]

CHAT_BOARD = {
    "id": "board:naukri", "archetype": "chat",
    "entry": {"selector": "#apply-button", "submits": "maybe"},
    "domains": ["board.test"],
    "questions": {"capture": "apply-workflow/v1/apply", "path": "jobs[0].questionnaire", "parser": "naukri"},
    "chat": {"container": "._chatBotContainer", "input": "div.textArea",
             "option": "label.mcc__label, label.ssrc__label", "send": "div.sendMsg",
             "done": "Thank you for your responses"},
    "confirm": [{"capture": "apply-workflow/v1/apply", "path": "jobs[0].message", "match": "successfully applied"},
                {"capture": "apply-workflow/v1/apply", "request_match": "applyData", "status": 200}],
    "logged_out": [], "interstitial": [],
}

CTC = "Expected CTC"


def _board_flow():
    """An entry whose click is judged submitting, with a real flow (final control) behind it."""
    return {"id": "board:test", "archetype": "form", "entry": {"selector": "#apply", "submits": "yes"},
            "final": ["Send application"], "advance": [],
            "confirm": [{"capture": "/api/confirm", "status": 200}],
            "logged_out": [], "interstitial": [], "uncheck": []}


def _board_one_click():
    """The instahyre/iimjobs shape: the entry click IS the application — nothing reversible behind it."""
    b = _board_flow()
    b["final"], b["advance"] = [], []
    return b


class _Req:
    def __init__(self, body=""):
        self.post_data = body


class _Resp:
    """A response-shaped object for signals.rule_matches / ChatDriver._questionnaire."""

    def __init__(self, url, data=None, body="", status=200):
        self.url, self.status = url, status
        self.request = _Req(body)
        self._data, self._body = data, body

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def text(self):
        return self._body


class FakeCapture:
    """run.Capture stand-in on one canned list of the page's own responses."""

    def __init__(self, responses=()):
        self.responses = list(responses)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeDeps:
    """BrowserDeps contract; the entry click flips to the next screen (the modal/bot)."""

    def __init__(self, screens):
        self.screens, self.i = screens, 0
        self.clicks, self.fill_calls = [], []

    def snapshot(self, page):
        return self.screens[min(self.i, len(self.screens) - 1)]

    def fill(self, page, decisions):
        self.fill_calls.append([d.ref for d in decisions])

    def click(self, page, label):
        self.clicks.append(label)
        page.text = "Thanks — your application is in"    # the board answers: the form is gone


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def type(self, text):
        self.page.log.append(("type", text))

    def press(self, key):
        self.page.log.append(("press", key))
        chat = getattr(self.page, "chat", None)
        if chat is not None and key == "Enter":
            chat.advance()                       # Enter sends the composed bubble on a chat page


class FakeChat:
    """The bot's conversation: each sent answer advances one bubble; after the LAST one
    the bot applies itself by POSTing applyData (naukri notes 2026-09-26)."""

    def __init__(self, config, turns, cap=None):
        self.config, self.turns, self.cap, self.turn, self.sent, self.picks = config, turns, cap, 0, 0, []

    def text(self):
        return self.turns[min(self.turn, len(self.turns) - 1)][0]

    def options(self):
        return self.turns[min(self.turn, len(self.turns) - 1)][1]

    def advance(self):
        self.sent += 1
        self.turn += 1
        if self.cap is not None and self.turn >= len(self.turns) - 1:
            if not any("applyData" in (r.request.post_data or "") for r in self.cap.responses):
                self.cap.responses.append(
                    _Resp("https://naukri.test/job-listings-x/apply-workflow/v1/apply",
                          body=json.dumps({"applyData": ["Yes", "2 Months"]})))


class _Loc:
    """Locator-shaped stand-in; every click is recorded (nothing is allowed to sneak past)."""

    def __init__(self, page, sel="", nth=0):
        self.page, self.sel, self._nth = page, sel, nth

    def filter(self, visible=None):
        return self

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def is_visible(self):
        return True

    def click(self, **kw):
        p, chat = self.page, getattr(self.page, "chat", None)
        if chat is not None and self.sel in (chat.config["send"], chat.config["option"],
                                             chat.config["input"], chat.config["container"]):
            if self.sel == chat.config["send"]:
                chat.advance()
            elif self.sel == chat.config["option"]:
                chat.picks.append(chat.options()[self._nth])
            else:
                p.log.append(("chat click", self.sel))
            return
        if self.sel == p.entry_sel:
            p.entry_clicked = True
            p.on_entry_click()
            return
        p.log.append(("click", self.sel))

    def wait_for(self, state, timeout=0):
        return None

    def evaluate(self, *a, **kw):
        return ""

    def uncheck(self, **kw):
        pass

    def count(self):
        chat = getattr(self.page, "chat", None)
        return len(chat.options()) if chat is not None and self.sel == chat.config["option"] else 0

    def inner_text(self):
        chat = getattr(self.page, "chat", None)
        if chat is not None and self.sel == chat.config["option"]:
            opts = chat.options()
            return opts[self._nth] if 0 <= self._nth < len(opts) else ""
        if chat is not None and self.sel == chat.config["container"]:
            return chat.text()
        return self.page.text

    def nth(self, i):
        return _Loc(self.page, self.sel, nth=i)


class FakePage:
    """The page surface run_board + the drivers touch — none of Playwright."""

    def __init__(self, url="http://board.test/job", text="Data Scientist at Acme",
                 screens=None, entry_sel="#apply"):
        self.url, self.text = url, text
        self.log, self.entry_sel, self.entry_clicked = [], entry_sel, False
        self.chat = None
        self.keyboard = FakeKeyboard(self)
        self.deps = FakeDeps(screens or [[]])
        self.context = self                    # new_tab_since reads context.pages

    def on_entry_click(self):
        self.deps.i = min(self.deps.i + 1, len(self.deps.screens) - 1)   # the entry click opens the flow

    @property
    def pages(self):
        return [self]

    def is_closed(self):
        return False

    def wait_for_timeout(self, ms):
        pass

    def title(self):
        return "Data Scientist | Acme"

    def inner_text(self, sel):
        return self.text

    def evaluate(self, js, *args):
        if "document.body" in js:
            return self.text
        if "application (sent|submitted)" in js:               # _APPLIED_BUTTON_JS
            return False
        if "[role=alert]" in js:                               # _ERRORS_JS
            return []
        if "closest('[role=dialog]" in js:                     # drivers._DIALOG_REFS_JS
            return [False] * len(args[0] if args else [])
        if "chat i" in js:                                     # chat diagnostics on failure
            return []
        return False                                           # dom_states / read_form_values / probes

    def locator(self, sel):
        return _Loc(self, sel)


class ChatPage(FakePage):
    """A naukri-shaped page: the bot lives in FakeChat, the page text stays the listing."""

    def __init__(self, chat_engine):
        super().__init__(text="Data Scientist job listing at Acme", entry_sel="#apply-button")
        self.chat = chat_engine

    def on_entry_click(self):
        self.entry_clicked = True                              # the entry never flips a chat screen


def _chat_page(cap, turns=None):
    turns = turns or [
        (f"{Q1}\nSave", ["Yes", "No", "Skip this question"]),   # the bot asks Q1 as a radio
        (f"{Q1}\n{Q2}\nSave", []),                             # the bot asks Q2 as a text box
        ("Thank you for your responses", []),                  # the bot's done text after the last answer
    ]
    return ChatPage(FakeChat(CHAT_BOARD["chat"], turns, cap))


class _NoHuman:
    """Nothing here asks the human: fill-probe runs pre-answered, one-click dry-run and
    probe all resolve before any question. Fail loudly if a run tries anyway."""

    def approve(self, card):
        raise AssertionError("run asked the human to authorize a submit in a no-submit test")

    def collect(self, fields):
        raise AssertionError("run asked questions: " + str([f.label for f in fields]))


class RecordingDriver(FormDriver):
    """FormDriver that records whether a run ever handed it ctx['fill_probe']."""

    def __init__(self):
        self.seen = []

    def put(self, page, board, ctx, fields, decisions):
        self.seen.append(ctx.get("fill_probe"))
        return super().put(page, board, ctx, fields, decisions)


def _answers_ladder(monkeypatch, decisions=()):
    """answer_fields seam (house pattern, as in test_board_run_browser._run): canned decisions
    or none, never a human ask."""
    from career_agent.boards import run as run_mod
    monkeypatch.setattr(run_mod, "answer_fields", lambda fields, c: (list(decisions), list(fields)))


def _run(page, board, monkeypatch, cap=None, **ctx):
    from career_agent.boards import run as run_mod
    cap = cap or FakeCapture()
    monkeypatch.setattr(run_mod, "Capture", lambda ctx_, needles: cap)
    return run_mod.run_board(page, board, {"deps": page.deps, "human": _NoHuman(), "profile": None, **ctx})


FORM_SCREEN = [Field("#ctc", "text", CTC, False, [], None, None),
               Field("#send", "button", "Send application", False, [], None, None)]


def test_fill_probe_fills_what_the_flow_holds_then_refuses_the_final_click(monkeypatch):
    """(a) The frozen shape: an entry whose click is judged submitting, a real flow (final
    control) behind it. Fill-probe runs the driver — the field is filled, the commit click
    never fires — and stops reached_submit_dry_run with the fill count carried."""
    _answers_ladder(monkeypatch, [FillDecision("#ctc", "text", CTC, "30 LPA", "fill", "profile")])
    page = FakePage(screens=[[], FORM_SCREEN])
    out = _run(page, _board_flow(), monkeypatch)
    assert out["stopped_reason"] == "reached_submit_dry_run", out
    assert [d["ref"] for d in out["decisions"]] == ["#ctc"]           # the fill count dashboards read
    assert page.deps.fill_calls == [["#ctc"]]                        # put actually filled it
    assert page.entry_clicked and page.deps.clicks == []             # entry clicked, final click refused
    assert out["submitted"] is False


def test_one_click_entry_keeps_the_old_dry_run(monkeypatch):
    """(b) The entry is the whole application (instahyre, iimjobs): nothing reversible sits
    before the commit, so the dry-run stop stays exactly as it was."""
    _answers_ladder(monkeypatch)
    page = FakePage()
    out = _run(page, _board_one_click(), monkeypatch)
    assert out["stopped_reason"] == "dry_run" and out["decisions"] == [] and out["submitted"] is False
    assert not page.entry_clicked and page.deps.fill_calls == []     # the commit never happened


def test_authorized_flow_never_learns_of_the_flag_and_still_submits(monkeypatch):
    """(c) A submit-authorized run of the same shape is as before: the driver put runs, the
    final click fires (authorized), the board's own response confirms — and the driver was
    never handed the flag."""
    _answers_ladder(monkeypatch, [FillDecision("#ctc", "text", CTC, "30 LPA", "fill", "profile")])
    rec = RecordingDriver()
    from career_agent.boards import run as run_mod
    monkeypatch.setattr(run_mod, "DRIVERS", {"form": rec})
    page = FakePage(screens=[[], FORM_SCREEN])
    cap = FakeCapture()
    click = page.deps.click
    page.deps.click = lambda pg, label: (click(pg, label),
                                         cap.responses.append(_Resp("http://board.test/api/confirm", status=200)))
    out = _run(page, _board_flow(), monkeypatch, cap=cap, do_submit=True, autonomous=True)
    assert out["submitted"] and out["stopped_reason"] == "submitted", out
    assert rec.seen == [None]                                        # the driver saw no fill_probe
    assert page.deps.clicks == ["Send application"]                  # the commit happened, authorized


def test_plain_form_dry_run_still_stops_at_its_final_button(monkeypatch):
    """The wellfound shape (entry opens the form, submits:no): the entry guard is not even
    reached — without fill_probe the final-control dry_run stop keeps its old name and
    carries the fills it always carried."""
    _answers_ladder(monkeypatch)
    b = {**_board_flow(), "entry": {"selector": "#apply", "submits": "no"}}
    page = FakePage(screens=[[], FORM_SCREEN])
    out = _run(page, b, monkeypatch)
    assert out["stopped_reason"] == "dry_run"                        # old name, no flag involved
    assert page.entry_clicked and page.deps.clicks == []             # entry opened, final click refused
    assert out["decisions"] == [] and out["submitted"] is False


def test_chat_fill_probe_answers_until_the_last_and_refuses_the_commit(monkeypatch):
    """The naukri shape: the chat questionnaire lives behind the entry; the bot applies
    itself after the last answer. Fill-probe composes and sends everything but THAT last
    answer, then stops reached_submit_dry_run with the composed answers counted and no
    apply POST anywhere."""
    _answers_ladder(monkeypatch)
    cap = FakeCapture([_Resp("https://naukri.test/job-listings-x#apply-workflow/v1/apply",
                             data={"jobs": [{"questionnaire": _QN}]})])
    page = _chat_page(cap)
    out = _run(page, CHAT_BOARD, monkeypatch, cap=cap)
    assert out["stopped_reason"] == "reached_submit_dry_run", out
    assert out["submitted"] is False and out["pending_human"] == []
    assert [d["ref"] for d in out["decisions"]] == ["q:1", "q:2"]     # both composed answers counted
    assert page.chat.sent == 1                                       # Q1 answered, Q2 withheld
    assert page.chat.picks == ["Yes"]                                # the radio option was really chosen
    assert ("type", "2 Months") not in page.log                      # the final answer was never typed
    assert not any("applyData" in (r.request.post_data or "") for r in cap.responses)  # no apply POST


def test_chat_authorized_run_answers_everything_and_confirms(monkeypatch):
    """(d) The authorized chat run is exactly as before: every question answered (option
    click + typed text, both sent), the bot's own apply response confirms."""
    _answers_ladder(monkeypatch)
    cap = FakeCapture([_Resp("https://naukri.test/job-listings-x#apply-workflow/v1/apply",
                             data={"jobs": [{"questionnaire": _QN}]})])
    page = _chat_page(cap)
    out = _run(page, CHAT_BOARD, monkeypatch, cap=cap, do_submit=True, autonomous=True)
    assert out["submitted"] and out["stopped_reason"] == "submitted", out
    assert page.chat.sent == 2 and ("type", "2 Months") in page.log   # Q1 sent, Q2 typed + sent
    assert any("applyData" in (r.request.post_data or "") for r in cap.responses)      # the bot's own POST


def test_probe_mode_is_unchanged(monkeypatch):
    """(d) Probe mode: the one-click entry is proven to exist and never clicked; nothing
    else ran. Same stop string, no fills, no flag introduced."""
    _answers_ladder(monkeypatch)
    page = FakePage()
    out = _run(page, _board_one_click(), monkeypatch, probe=True)
    assert out["stopped_reason"] == "probe" and out["decisions"] == []
    assert not page.entry_clicked and page.deps.fill_calls == []
