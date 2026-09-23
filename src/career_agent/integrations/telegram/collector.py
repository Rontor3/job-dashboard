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

import re
import time

# Labels that ask why the candidate wants this company/role — include JD context.
_COMPANY_Q_RE = re.compile(
    r"why\s+(this\s+)?(company|role|join|apply|us\b|our)"
    r"|motivat|what.{0,20}attract"
    r"|interest\s+in\s+(this|the)\s+(role|position|company|job)"
    r"|tell\s+us\s+why",
    re.I,
)

_YES = {"yes", "y", "true", "sure"}
_NO = {"no", "n", "false", "nope"}
_SKIP = {"skip", "-", "none", "n/a", "na"}
# Placeholder labels perception couldn't resolve — asking about them is nonsense.
_JUNK = {"", "select...", "select", "select an option", "select one",
         "please select", "choose", "choose...", "choose one", "-"}


class TelegramCollector:
    def __init__(self, client, drafter=None, context="", deadline_s=900,
                 text_deadline_s=1800,
                 poll_interval_s=2, sleep=time.sleep, jd_text=None):
        self.client = client
        self.drafter = drafter                 # (label) -> suggested answer | None
        self.context = context                 # e.g. "Anthropic · Data Scientist"
        self.deadline_s = deadline_s
        self.text_deadline_s = text_deadline_s  # longer wait for free-text iteration
        self.poll_interval_s = poll_interval_s
        self._sleep = sleep
        self.jd_text = jd_text                 # scraped from JD page; None if unavailable
        # Populated after each __call__: {ref: "approve" | "edit"}
        self._last_events: dict[str, str] = {}
        # Draft shown per ref — used by caller to determine approve vs edit
        self._last_drafts: dict[str, str] = {}

    def _head(self):
        return f"{self.context} —\n" if self.context else ""

    def _await(self, deadline_s: int | None = None):
        waited = 0
        limit = deadline_s if deadline_s is not None else self.deadline_s
        while waited < limit:
            r = self.client.poll_text(self.poll_interval_s)
            if r is not None:
                return r
            self._sleep(self.poll_interval_s)
            waited += self.poll_interval_s or 1
        return None

    def _jd_block(self, label: str) -> str:
        """Return a JD context header if label is a company/role question and jd_text is set."""
        if self.jd_text and _COMPANY_Q_RE.search(label or ""):
            excerpt = self.jd_text[:1500].strip()
            return f"📄 Role context:\n{excerpt}\n\n"
        return ""

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
        self._last_events = {}
        self._last_drafts = {}
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
                    self._last_events[f.ref] = "approve"
                elif low in _NO:
                    out[f.ref] = "No"
                    self._last_events[f.ref] = "approve"
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
                    self._last_events[f.ref] = "approve"
                continue

            if f.kind == "textarea":
                draft = None
                if self.drafter:
                    try:
                        draft = self.drafter(label)
                    except Exception:
                        draft = None
                if draft:
                    self._last_drafts[f.ref] = draft
                jd_block = self._jd_block(label)
                if draft:
                    self.client.send_message(
                        f"{self._head()}Application question:\n\n\"{label}\"\n\n"
                        f"{jd_block}"
                        f"Here's a draft I put together from your profile:\n"
                        f"———\n{draft}\n———\n"
                        "Reply *ok* to use as-is, send your version to iterate, "
                        "*done* to finalize your last edit, or *skip* to leave blank.")
                else:
                    self.client.send_message(
                        f"{self._head()}Please answer:\n\n\"{label}\"\n\n"
                        f"{jd_block}"
                        "Type your answer (*done* to finalize, or *skip* to leave blank).")
                # Iteration loop — user can refine until "ok" / "done" / timeout
                current = draft
                while True:
                    r = self._await(deadline_s=self.text_deadline_s)
                    if r is None:
                        break
                    low = r.strip().lower()
                    if low in _SKIP:
                        current = None
                        break
                    if low == "ok" and draft:
                        current = draft
                        self._last_events[f.ref] = "approve"
                        break
                    if low == "done":
                        if current != draft:
                            self._last_events[f.ref] = "edit"
                        else:
                            self._last_events[f.ref] = "approve"
                        break
                    # User sent a new version — keep going
                    current = r.strip()
                    self.client.send_message(
                        "Got it. Reply with more edits or *done* to finalize.")
                if current:
                    out[f.ref] = current
                    if f.ref not in self._last_events:
                        self._last_events[f.ref] = "edit" if current != draft else "approve"
                continue

            # combobox / text / anything else -> free text; the combobox filler
            # opens the widget and maps a typed value to a live option.
            jd_block = self._jd_block(label)
            self.client.send_message(
                f"{self._head()}Please answer:\n\n\"{label}\"\n\n"
                f"{jd_block}"
                "Type your answer (or *skip*).")
            r = self._await()
            if r and r.strip().lower() not in _SKIP:
                out[f.ref] = r
                self._last_events[f.ref] = "approve"
        return out
