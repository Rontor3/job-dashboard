"""Collect escalated fields over Telegram, adapting the prompt to the field
type so the answer is unambiguous on a phone:

  textarea  -> a qwen DRAFT to accept ("ok") or edit
  select/radio (options known) -> a numbered list; reply a number
  checkbox  -> reply yes/no
  combobox/text -> type the value (the combobox filler maps it to a live option)
  file      -> not asked; left to attach in the browser

Every prompt carries a context header (which application) and a "skip" option.
Fields whose label is an unresolved placeholder ("Select...") are skipped — they
are unanswerable over text — and left for the browser. Contract matches
CliCollector: __call__(fields) -> {ref: value}. Resolved answers are filled AND
recorded by the learning loop upstream."""
from __future__ import annotations

import time

_YES = {"yes", "y", "true", "sure"}
_NO = {"no", "n", "false", "nope"}
_SKIP = {"skip", "-", "none", "n/a", "na"}
# Placeholder labels perception couldn't resolve — asking about them is nonsense.
_JUNK = {"", "select...", "select", "select an option", "select one",
         "please select", "choose", "choose...", "choose one", "-"}


class TelegramCollector:
    def __init__(self, client, drafter=None, context="", deadline_s=900,
                 poll_interval_s=2, sleep=time.sleep):
        self.client = client
        self.drafter = drafter                 # (label) -> suggested answer | None
        self.context = context                 # e.g. "Anthropic · Data Scientist"
        self.deadline_s = deadline_s
        self.poll_interval_s = poll_interval_s
        self._sleep = sleep

    def _head(self):
        return f"{self.context} —\n" if self.context else ""

    def _await(self):
        waited = 0
        while waited < self.deadline_s:
            r = self.client.poll_text(self.poll_interval_s)
            if r is not None:
                return r
            self._sleep(self.poll_interval_s)
            waited += self.poll_interval_s or 1
        return None

    @staticmethod
    def _match_option(reply, options):
        r = (reply or "").strip()
        if r.isdigit():
            i = int(r) - 1
            if 0 <= i < len(options):
                return options[i]
        for o in options:
            if o.strip().lower() == r.lower():
                return o
        return None

    def __call__(self, fields) -> dict:
        out: dict = {}
        drain = getattr(self.client, "drain", None)
        if drain:
            drain()               # discard stale updates so they aren't read as answers
        for f in fields:
            label = (f.label or "").strip() or f.ref
            if f.kind != "file" and label.strip().lower() in _JUNK:
                continue                       # unresolved placeholder -> leave for browser

            if f.kind == "file":
                self.client.send_message(
                    f"📎 {self.context + ' — ' if self.context else ''}"
                    f"\"{label}\" needs a file upload. I'll leave this one for you "
                    "to attach directly in the browser.")
                continue

            if f.kind == "checkbox":
                self.client.send_message(
                    f"{self._head()}Yes or no?\n\n\"{label}\"\n\n"
                    "Reply *yes* or *no* (or *skip* to leave it).")
                r = self._await()
                low = (r or "").strip().lower()
                if low in _SKIP:
                    continue
                if low in _YES:
                    out[f.ref] = "Yes"
                elif low in _NO:
                    out[f.ref] = "No"
                continue

            if f.kind in ("select", "radio_group") and f.options:
                body = "\n".join(f"  {i+1}) {o}" for i, o in enumerate(f.options))
                self.client.send_message(
                    f"{self._head()}Pick one — reply with a number:\n\n"
                    f"\"{label}\"\n{body}\n\n(or *skip* to leave it)")
                r = self._await()
                if r is None or r.strip().lower() in _SKIP:
                    continue
                opt = self._match_option(r, f.options)
                if opt is not None:
                    out[f.ref] = opt
                continue

            if f.kind == "textarea":
                draft = None
                if self.drafter:
                    try:
                        draft = self.drafter(label)
                    except Exception:
                        draft = None
                if draft:
                    self.client.send_message(
                        f"{self._head()}Application question:\n\n\"{label}\"\n\n"
                        f"Here's a draft I put together from your profile:\n"
                        f"———\n{draft}\n———\n"
                        "Reply *ok* to use it as-is, send your edited version, "
                        "or *skip* to leave it blank.")
                else:
                    self.client.send_message(
                        f"{self._head()}Please answer:\n\n\"{label}\"\n\n"
                        "Type your answer (or *skip*).")
                r = self._await()
                if r is None or r.strip().lower() in _SKIP:
                    continue
                out[f.ref] = draft if (draft and r.strip().lower() == "ok") else r
                continue

            # combobox / text / anything else -> free text; the combobox filler
            # opens the widget and maps a typed value to a live option.
            self.client.send_message(
                f"{self._head()}Please answer:\n\n\"{label}\"\n\n"
                "Type your answer (or *skip*).")
            r = self._await()
            if r and r.strip().lower() not in _SKIP:
                out[f.ref] = r
        return out
