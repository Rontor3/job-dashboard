from career_agent.integrations.telegram.client import TelegramClient


class FakeTransport:
    def __init__(self, responses): self.responses = responses; self.calls = []
    def __call__(self, method, payload):
        self.calls.append((method, payload))
        return self.responses.pop(0)


def test_send_message_builds_inline_keyboard():
    t = FakeTransport([{"ok": True, "result": {"message_id": 7}}])
    c = TelegramClient("tok", "42", transport=t)
    mid = c.send_message("hi", buttons=[[("Submit", "submit")], [("Skip", "skip")]])
    assert mid == 7
    method, payload = t.calls[0]
    assert method == "sendMessage"
    assert payload["chat_id"] == "42"
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "submit"


def test_poll_callback_returns_matching_data():
    upd = {"ok": True, "result": [
        {"update_id": 1, "callback_query": {"id": "x", "data": "submit"}}]}
    t = FakeTransport([upd, {"ok": True, "result": []}])
    c = TelegramClient("tok", "42", transport=t)
    assert c.poll_callback(timeout_s=0, valid={"submit", "skip"}) == "submit"


def test_poll_callback_ignores_unknown_and_times_out():
    upd = {"ok": True, "result": [
        {"update_id": 1, "callback_query": {"id": "x", "data": "other"}}]}
    t = FakeTransport([upd])
    c = TelegramClient("tok", "42", transport=t)
    assert c.poll_callback(timeout_s=0, valid={"submit"}) is None


def test_poll_text_returns_message_text_from_our_chat():
    upd = {"ok": True, "result": [
        {"update_id": 5, "message": {"chat": {"id": 42}, "text": " Male "}}]}
    t = FakeTransport([upd])
    c = TelegramClient("tok", "42", transport=t)
    assert c.poll_text(timeout_s=0) == "Male"        # trimmed


def test_poll_text_ignores_other_chats_and_times_out():
    upd = {"ok": True, "result": [
        {"update_id": 6, "message": {"chat": {"id": 999}, "text": "nope"}}]}
    t = FakeTransport([upd])
    c = TelegramClient("tok", "42", transport=t)
    assert c.poll_text(timeout_s=0) is None


def test_poll_text_advances_offset():
    upd = {"ok": True, "result": [
        {"update_id": 8, "message": {"chat": {"id": 42}, "text": "hi"}}]}
    t = FakeTransport([upd])
    c = TelegramClient("tok", "42", transport=t)
    c.poll_text(timeout_s=0)
    assert c._offset == 9


def test_drain_advances_offset_past_all_pending():
    upd = {"ok": True, "result": [
        {"update_id": 10, "message": {"chat": {"id": 42}, "text": "old1"}},
        {"update_id": 12, "message": {"chat": {"id": 42}, "text": "old2"}}]}
    t = FakeTransport([upd])
    c = TelegramClient("tok", "42", transport=t)
    c.drain()
    assert c._offset == 13                       # past the highest pending update
    method, payload = t.calls[0]
    assert method == "getUpdates"


def test_drain_noop_when_nothing_pending():
    t = FakeTransport([{"ok": True, "result": []}])
    c = TelegramClient("tok", "42", transport=t)
    c.drain()
    assert c._offset == 0


def test_poll_callback_answers_the_matched_button_so_phone_stops_spinning():
    upd = {"ok": True, "result": [
        {"update_id": 5, "callback_query": {"id": "cb9", "data": "abort"}}]}
    t = FakeTransport([upd, {"ok": True, "result": True}])  # 2nd = answerCallbackQuery
    c = TelegramClient("tok", "42", transport=t)
    assert c.poll_callback(timeout_s=0, valid={"abort"}) == "abort"
    answers = [p for (m, p) in t.calls if m == "answerCallbackQuery"]
    assert answers and answers[0]["callback_query_id"] == "cb9"


def test_answer_callback_posts_id_and_optional_text():
    t = FakeTransport([{"ok": True, "result": True}])
    c = TelegramClient("tok", "42", transport=t)
    c.answer_callback("cb1", text="Working…")
    method, payload = t.calls[0]
    assert method == "answerCallbackQuery"
    assert payload == {"callback_query_id": "cb1", "text": "Working…"}

