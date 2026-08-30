"""Thin Telegram Bot API client. Transport is injected (tests fake it);
the default hits api.telegram.org via httpx."""
from __future__ import annotations

from typing import Callable

Transport = Callable[[str, dict], dict]


def _default_transport(token: str) -> Transport:
    def _t(method: str, payload: dict) -> dict:
        import httpx
        url = f"https://api.telegram.org/bot{token}/{method}"
        return httpx.post(url, json=payload, timeout=65).json()
    return _t


class TelegramClient:
    def __init__(self, token: str, chat_id: str, transport: Transport | None = None):
        self.chat_id = chat_id
        self._t = transport or _default_transport(token)
        self._offset = 0

    def send_message(self, text: str, buttons=None) -> int:
        payload = {"chat_id": self.chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [
                [{"text": label, "callback_data": data} for (label, data) in row]
                for row in buttons]}
        resp = self._t("sendMessage", payload)
        return resp.get("result", {}).get("message_id", 0)

    def poll_callback(self, timeout_s: int, valid: set[str]) -> str | None:
        payload = {"timeout": timeout_s, "offset": self._offset,
                   "allowed_updates": ["callback_query"]}
        resp = self._t("getUpdates", payload)
        for upd in resp.get("result", []):
            self._offset = max(self._offset, upd["update_id"] + 1)
            data = upd.get("callback_query", {}).get("data")
            if data in valid:
                return data
        return None

    def poll_text(self, timeout_s: int) -> str | None:
        """One long-poll for a text reply from our chat. Returns the trimmed
        message text, or None if nothing arrived this round."""
        payload = {"timeout": timeout_s, "offset": self._offset,
                   "allowed_updates": ["message"]}
        resp = self._t("getUpdates", payload)
        for upd in resp.get("result", []):
            self._offset = max(self._offset, upd["update_id"] + 1)
            msg = upd.get("message", {})
            if str(msg.get("chat", {}).get("id")) == str(self.chat_id):
                text = (msg.get("text") or "").strip()
                if text:
                    return text
        return None
