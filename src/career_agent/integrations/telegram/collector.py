"""Collect escalated fields over Telegram, adapting the prompt to the field
type so the answer is unambiguous on a phone:

  textarea  -> a qwen DRAFT to accept ("ok") or edit
  select/radio (options known) -> a numbered list; reply a number
  checkbox  -> reply yes/no
  combobox/text -> type the value (the combobox filler maps it to a live option)
  file      -> not asked; left to attach in the browser

Contract matches CliCollector: __call__(fields) -> {ref: value}. Whatever
resolves is filled AND recorded by the learning loop upstream."""
from __future__ import annotations

import time

_YES = {"yes", "y", "true", "ok", "sure"}
_NO = {"no", "n", "false", "nope"}


class TelegramCollector:
    def __init__(self, client, drafter=None, deadline_s=900, poll_interval_s=2, sleep=time.sleep):
        self.client = client
        self.drafter = drafter                 # (label) -> suggested answer | None
        self.deadline_s = deadline_s
        self.poll_interval_s = poll_interval_s
        self._sleep = sleep

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
        for f in fields:
            label = f.label or f.ref
            if f.kind == "file":
                self.client.send_message(f"\U0001F4CE \"{label}\" needs a file — attach it in the browser.")
                continue
            if f.kind == "checkbox":
                self.client.send_message(f"☑️ Reply yes or no:\n\"{label}\"")
                r = self._await()
                if r and r.strip().lower() in _YES:
                    out[f.ref] = "Yes"
                elif r and r.strip().lower() in _NO:
                    out[f.ref] = "No"
                continue
            if f.kind in ("select", "radio_group") and f.options:
                body = "\n".join(f"  {i+1}) {o}" for i, o in enumerate(f.options))
                self.client.send_message(
                    f"\U0001F53D Reply 1–{len(f.options)}:\n\"{label}\"\n{body}")
                r = self._await()
                opt = self._match_option(r, f.options) if r else None
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
                        f"✏️ \"{label}\"\nSuggested:\n{draft}\n\n"
                        "Reply \"ok\" to use it, or send your edited version.")
                else:
                    self.client.send_message(f"✏️ Type your answer:\n\"{label}\"")
                r = self._await()
                if r is None:
                    continue
                out[f.ref] = draft if (draft and r.strip().lower() == "ok") else r
                continue
            # combobox / text / anything else -> free text; the combobox filler
            # opens the widget and maps a typed value to a live option.
            self.client.send_message(f"✏️ Type the value:\n\"{label}\"")
            r = self._await()
            if r:
                out[f.ref] = r
        return out
