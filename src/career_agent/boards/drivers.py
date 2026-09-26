"""Board drivers. `form` covers one-click boards (zero pages) and multi-page
wizards (LinkedIn Easy Apply, Indeed SmartApply, Wellfound's modal); `chat`
covers Naukri's chatbot. Both expose fields / prefill / put / next_control /
click; run.py owns the loop, the submit gate and confirmation."""
from __future__ import annotations

import re

from . import questions as _q
from .profiles import json_path


def _norm(s):
    return re.sub(r"\W+", " ", str(s or "").lower()).strip()


class FormDriver:
    def _snapshot(self, page, ctx):
        # Anything already on the page before the entry click is page chrome
        # (search boxes, language pickers, footer buttons) — never the form.
        base = ctx.get("baseline", set())
        return [f for f in ctx["deps"].snapshot(page) if (f.label, f.kind) not in base]

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
            page.locator(f'button:has-text("{label}")').last.click(timeout=5000)
            page.wait_for_timeout(2500)


class ChatDriver(FormDriver):
    """Naukri-style chatbot: the questionnaire arrives as JSON in the apply
    response; answers go in one bubble at a time until the bot's done text.
    With no questionnaire (instant apply) it behaves as a zero-page form."""

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
                box.wait_for(timeout=8000)
                text = _norm(box.inner_text())
            except Exception:
                return
            if _norm(chat["done"]) in text:
                return
            asked = [f for f in pending if _norm(f.label) in text]
            if not asked:
                return                        # bot asked something we hold no answer for
            f = max(asked, key=lambda f: text.rfind(_norm(f.label)))   # the latest bubble
            pending.remove(f)
            self._answer(page, chat, str(values[f.ref]))
            page.wait_for_timeout(2500)

    def _answer(self, page, chat, value):
        opts, hit = page.locator(chat["option"]), False
        for i in range(opts.count()):
            o = opts.nth(i)
            t = _norm(o.inner_text())
            if t and (t in _norm(value) or _norm(value) in t):
                o.click()
                hit = True
        if hit:
            page.locator(chat["send"]).last.click()
            return
        page.locator(chat["input"]).last.click()
        page.keyboard.type(value)
        page.keyboard.press("Enter")


DRIVERS = {"form": FormDriver(), "chat": ChatDriver()}
