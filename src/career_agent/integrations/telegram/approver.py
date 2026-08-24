"""Telegram-backed Approver: sends the review card with Submit/Skip buttons
and blocks until the user taps one (or the deadline passes)."""
from __future__ import annotations

import time

_BUTTONS = [[("✅ Submit", "submit"), ("🚫 Skip", "skip")]]
_VALID = {"submit", "skip"}


class TelegramApprover:
    def __init__(self, client, poll_interval_s: int = 2, deadline_s: int = 1800,
                 sleep=time.sleep, clock=time.monotonic):
        self.client = client
        self.poll_interval_s = poll_interval_s
        self.deadline_s = deadline_s
        self._sleep = sleep
        self._clock = clock

    def request(self, card: str) -> bool:
        self.client.send_message(card, buttons=_BUTTONS)
        start = self._clock()
        while True:
            choice = self.client.poll_callback(timeout_s=self.poll_interval_s, valid=_VALID)
            if choice == "submit":
                return True
            if choice == "skip":
                return False
            if self._clock() - start >= self.deadline_s:
                return False
            self._sleep(self.poll_interval_s)
