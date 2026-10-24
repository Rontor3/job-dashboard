"""A kept-alive connection to Telegram that went stale while the run filled a form fails its next call with
RemoteProtocolError (Opella, live 2026-10-24: the question never reached the phone). One retry on a fresh one."""
import httpx

import career_agent.integrations.telegram.client as tg


def test_a_stale_connection_is_replaced_once(monkeypatch):
    made = []

    class FakeClient:
        def __init__(self, *a, **k):
            self.n = len(made); made.append(self)
        def post(self, url, json=None):
            if self.n == 0:
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    c = tg.TelegramClient("tok", "123")
    assert c.send_message("Opella: How did you hear about us?") == 7
    assert len(made) == 2                                   # the stale one, then one fresh connection
