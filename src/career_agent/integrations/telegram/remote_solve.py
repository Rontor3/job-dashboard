"""Remote-solve Telegram notifier: sends the phone the challenge type, the
tap-to-solve live-view link, and a TTL countdown with an Abort button; then
watches (in a background thread) for an Abort tap and reports the outcome.

Messaging and cancellation only — it never solves the challenge. The human
solves it in the live session; this just tells them where and lets them cancel.
"""
from __future__ import annotations

import threading
import time

_ABORT_BUTTONS = [[("🛑 Abort", "abort")]]
_ABORT_DATA = {"abort"}

_GATE_LABELS = {
    "recaptcha_v2_checkbox": "reCAPTCHA checkbox",
    "recaptcha_v2_image": "reCAPTCHA image challenge",
    "hcaptcha_checkbox": "hCaptcha checkbox",
    "hcaptcha_image": "hCaptcha image challenge",
}

_CLEARED = "✅ Cleared — continuing."
_ABORTED = "🛑 Aborted — the run is parked, nothing submitted."
_TIMEOUT = "⏳ Still blocked — resend the link or abort."


def _label(gate: str) -> str:
    return _GATE_LABELS.get(gate, gate.replace("_", " "))


def format_message(url: str, gate: str, deadline_s: int) -> str:
    mins = max(1, round(deadline_s / 60))
    return (
        f"🔐 Human solve needed: {_label(gate)}\n\n"
        f"Tap to open the live browser on your phone and solve it yourself:\n"
        f"{url}\n\n"
        f"⏳ Link valid ~{mins} min ({deadline_s}s). Tap Abort to cancel this solve."
    )


def _default_spawn(target):
    th = threading.Thread(target=target, daemon=True)
    th.start()
    return th


class RemoteSolveNotifier:
    def __init__(self, client, poll_interval_s: int = 2, sleep=time.sleep, spawn=None):
        self.client = client
        self.poll_interval_s = poll_interval_s
        self._sleep = sleep
        self._spawn = spawn or _default_spawn
        self._abort = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._started = False
        self._outcome_sent = False

    def start(self, url: str, gate: str, deadline_s: int) -> threading.Event:
        """Send the card and begin watching for an Abort tap. Returns the
        abort Event the RemoteSolveSession polls to cancel the wait."""
        self.client.send_message(format_message(url, gate, deadline_s),
                                 buttons=_ABORT_BUTTONS)
        self._started = True
        self._thread = self._spawn(self._watch)
        return self._abort

    def _watch(self) -> None:
        while not self._stop.is_set() and not self._abort.is_set():
            if self.client.poll_callback(self.poll_interval_s, _ABORT_DATA) == "abort":
                self._abort.set()
                return
            if self._stop.is_set():
                return
            self._sleep(self.poll_interval_s)

    def close(self, cleared: bool | None = None) -> None:
        """Stop the watcher and (once) report the outcome. Safe to call even if
        start() never ran or the live view failed to stand up."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=self.poll_interval_s + 1)
        if self._started and cleared is not None and not self._outcome_sent:
            self._outcome_sent = True
            self.client.send_message(
                _CLEARED if cleared else (_ABORTED if self._abort.is_set() else _TIMEOUT))
