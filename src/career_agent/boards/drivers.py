"""Board drivers. `form` covers one-click boards (zero pages) and multi-page
wizards (LinkedIn Easy Apply, Indeed SmartApply, Wellfound's modal); `chat`
covers Naukri's chatbot. Both expose fields / prefill / put / next_control /
click; run.py owns the loop, the submit gate and confirmation."""
from __future__ import annotations

import re

from ..browser.perception import frame_target
from . import questions as _q
from .profiles import json_path

_DIALOG = "[role=dialog],[aria-modal=true],[class*=modal i]"


_DIALOG_REFS_JS = """(refs) => refs.map(r => { try {
    let el = null;
    if (r.startsWith('group:')) el = document.querySelector('input[name="' + CSS.escape(r.slice(6)) + '"]');
    else if (r.startsWith('button:')) el = [...document.querySelectorAll('button')].find(b => (b.innerText || '').trim() === r.slice(7));
    else el = document.querySelector(r);
    return !!(el && el.closest('[role=dialog],[aria-modal=true],[class*=modal i]'));
  } catch (e) { return false; } })"""


def _dialog_refs(page, refs):
    """{ref: True} for top-frame refs sitting inside an open dialog — ONE browser
    round-trip for all of them (a per-field check cost minutes on LinkedIn)."""
    top = [r for r in refs if "@@" not in r]
    try:
        flags = page.evaluate(_DIALOG_REFS_JS, top)
    except Exception:
        return set()
    return {r for r, inside in zip(top, flags) if inside}


def _in_dialog(page, ref):
    """Is the element behind a perception ref inside an open dialog/modal?"""
    try:
        target, sel = frame_target(page, ref)
        if sel.startswith("group:"):
            loc = target.locator(f'input[name="{sel[6:]}"]')
        elif sel.startswith("button:"):
            loc = target.get_by_role("button", name=sel[7:], exact=True)
        else:
            loc = target.locator(sel)
        return bool(loc.first.evaluate(f"e => !!e.closest({_DIALOG!r})", timeout=1500))
    except Exception:
        return False


def _norm(s):
    return re.sub(r"\W+", " ", str(s or "").lower()).strip()


class FormDriver:
    ask_optional_upfront = False           # optional gaps asked only if the form won't advance

    def _snapshot(self, page, ctx):
        # Anything already on the page before the entry click is page chrome
        # (search boxes, language pickers, footer buttons) — unless it sits in
        # an open dialog: a board may render its apply modal before the click
        # (Wellfound re-opens an interrupted application on load).
        base = ctx.get("baseline", set())
        fields = ctx["deps"].snapshot(page)
        old = [f for f in fields if (f.label, f.kind) in base]
        inside = _dialog_refs(page, [f.ref for f in old]) if old else set()
        return [f for f in fields if (f.label, f.kind) not in base or f.ref in inside]

    def fields(self, page, board, ctx, cap):
        return [f for f in self._snapshot(page, ctx) if f.kind != "button"]

    def prefill(self, board, cap):
        return {}

    def put(self, page, board, ctx, fields, decisions):
        ctx["deps"].fill(page, decisions)

    def next_control(self, page, board, ctx):
        """(button label, is_final) for the next click, final names first; else None."""
        buttons = [f.label for f in self._snapshot(page, ctx) if f.kind == "button" and f.label]
        for names, final in ((board["final"], True), (board["advance"], False)):
            for n in names:
                for b in buttons:
                    if _norm(b).startswith(_norm(n)):
                        return b, final
        return None

    def click(self, page, label, ctx):
        try:
            ctx["deps"].click(page, label)
        except Exception:
            # Shadow-DOM buttons (LinkedIn Easy Apply): Playwright CSS locators
            # pierce open shadow roots where get_by_role may not.
            page.locator(f'button:has-text("{label}")').last.click(timeout=5000, no_wait_after=True)
            page.wait_for_timeout(2500)


class ChatDriver(FormDriver):
    """Naukri-style chatbot: the questionnaire arrives as JSON in the apply
    response; answers go in one bubble at a time until the bot's done text.
    With no questionnaire (instant apply) it behaves as a zero-page form."""
    ask_optional_upfront = True            # the bot asks every question; have all answers first

    def _questionnaire(self, board, cap):
        q = board.get("questions") or {}
        for r in reversed(cap.responses):
            if q.get("capture") and q["capture"] in r.url:
                try:
                    items = json_path(r.json(), q["path"])
                except Exception:
                    items = None
                if items:
                    return items
        return None

    def _parsed(self, board, cap):
        items = self._questionnaire(board, cap)
        return _q.PARSERS[board["questions"]["parser"]](items) if items else ([], {})

    def fields(self, page, board, ctx, cap):
        return self._parsed(board, cap)[0]

    def prefill(self, board, cap):
        return self._parsed(board, cap)[1]

    def next_control(self, page, board, ctx):
        return None                          # the bot submits itself after the last answer

    def put(self, page, board, ctx, fields, decisions):
        chat, values = board["chat"], {d.ref: d.value for d in decisions}
        pending = [f for f in fields if f.ref in values]
        box = page.locator(chat["container"]).first
        for _ in range(len(pending) + 2):
            try:
                # Naukri's wrapper has zero size (content overflows it), so Playwright
                # calls it "hidden": wait for it to be attached, not visible.
                box.wait_for(state="attached", timeout=8000)
                text = _norm(box.inner_text())
            except Exception:
                try:
                    seen = page.evaluate("""() => [...document.querySelectorAll('[class*=chat i],[id*=chat i]')]
                        .filter(e => e.checkVisibility()).map(e => (e.className || e.id).toString().slice(0, 50) + ' :: ' +
                        (e.innerText || '').slice(0, 80).replace(/\\n/g, ' ')).slice(0, 5)""")
                except Exception:
                    seen = "?"
                print(f"[board] chat container {chat['container']!r} not found; chat-like elements: {seen}", flush=True)
                return
            if _norm(chat["done"]) in text:
                return
            asked = [f for f in pending if _norm(f.label) in text]
            if not asked:
                print(f"[board] chat asked something not in our answers: {text[-160:]!r}", flush=True)
                return                        # bot asked something we hold no answer for
            f = max(asked, key=lambda f: text.rfind(_norm(f.label)))   # the latest bubble
            pending.remove(f)
            self._answer(page, chat, str(values[f.ref]))
            page.wait_for_timeout(2500)

    def _answer(self, page, chat, value):
        opts, hit = page.locator(chat["option"]), False
        want = _norm(value)
        labels = [(i, _norm(opts.nth(i).inner_text())) for i in range(opts.count())]
        # An exact option wins ("No" must not match "Not sure" / "Skip this question").
        picks = [i for i, t in labels if t and t == want] or \
                [i for i, t in labels if t and not t.startswith("skip") and (t in want or want in t)]
        for i in picks:
            opts.nth(i).click()
            hit = True
        if hit:
            page.locator(chat["send"]).last.click()
            return
        page.locator(chat["input"]).last.click()
        page.keyboard.type(value)
        page.keyboard.press("Enter")


DRIVERS = {"form": FormDriver(), "chat": ChatDriver()}
