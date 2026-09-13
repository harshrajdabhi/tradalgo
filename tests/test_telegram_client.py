import pytest

from tradalgo.notify.telegram import TelegramClient, TelegramError


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))
        if self.responses:
            resp = self.responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp
        return FakeResponse({"ok": True, "result": {}})


def make_client(responses=None, token="SECRET_TOKEN"):
    http = FakeSession(responses)
    return TelegramClient(token=token, chat_id="123", http=http), http


def test_send_message_returns_message_id():
    client, http = make_client([FakeResponse({"ok": True, "result": {"message_id": 55}})])
    message_id = client.send_message("hello")
    assert message_id == 55
    url, payload, timeout = http.calls[0]
    assert "SECRET_TOKEN" in url
    assert payload["chat_id"] == "123"
    assert payload["parse_mode"] == "HTML"
    assert "reply_markup" not in payload


def test_send_message_broadcasts_to_comma_separated_chat_ids():
    http = FakeSession([FakeResponse({"ok": True, "result": {"message_id": 55}}),
                        FakeResponse({"ok": True, "result": {"message_id": 999}})])
    client = TelegramClient(token="SECRET_TOKEN", chat_id=" 123 , 456 ", http=http)
    assert client.chat_id == "123"
    message_id = client.send_message("hi", buttons=[[("A", "a:1")]])
    assert message_id == 55  # the primary chat's id is what callers track for edit_message
    assert [c[1]["chat_id"] for c in http.calls] == ["123", "456"]
    assert "reply_markup" in http.calls[0][1]
    assert "reply_markup" not in http.calls[1][1]  # extra chats never get interactive buttons


def test_send_message_ignores_a_failing_extra_chat():
    http = FakeSession([FakeResponse({"ok": True, "result": {"message_id": 55}}),
                        FakeResponse({"ok": False, "description": "bot was blocked by the user"})])
    client = TelegramClient(token="SECRET_TOKEN", chat_id="123,456", http=http)
    assert client.send_message("hi") == 55


def test_send_message_with_buttons_builds_inline_keyboard():
    client, http = make_client([FakeResponse({"ok": True, "result": {"message_id": 1}})])
    client.send_message("hi", buttons=[[("A", "a:1"), ("B", "b:1")]])
    _, payload, _ = http.calls[0]
    assert payload["reply_markup"] == {"inline_keyboard": [[
        {"text": "A", "callback_data": "a:1"}, {"text": "B", "callback_data": "b:1"},
    ]]}


def test_api_error_raises_telegram_error_with_description():
    client, _ = make_client([FakeResponse({"ok": False, "description": "chat not found"})])
    with pytest.raises(TelegramError, match="chat not found"):
        client.send_message("hi")


def test_http_exception_raises_telegram_error():
    import requests
    client, _ = make_client([requests.ConnectionError("boom")])
    with pytest.raises(TelegramError):
        client.send_message("hi")


def test_edit_message_none_buttons_omits_reply_markup():
    client, http = make_client([FakeResponse({"ok": True, "result": {}})])
    client.edit_message(10, "updated text")
    _, payload, _ = http.calls[0]
    assert "reply_markup" not in payload


def test_edit_message_empty_buttons_clears_keyboard():
    client, http = make_client([FakeResponse({"ok": True, "result": {}})])
    client.edit_message(10, "updated text", buttons=[])
    _, payload, _ = http.calls[0]
    assert payload["reply_markup"] == {"inline_keyboard": []}


def test_answer_callback():
    client, http = make_client([FakeResponse({"ok": True, "result": True})])
    client.answer_callback("cbid", text="done")
    _, payload, _ = http.calls[0]
    assert payload == {"callback_query_id": "cbid", "text": "done"}


def test_get_updates_returns_list():
    updates = [{"update_id": 1}, {"update_id": 2}]
    client, http = make_client([FakeResponse({"ok": True, "result": updates})])
    result = client.get_updates(offset=5, timeout=0)
    assert result == updates
    _, payload, _ = http.calls[0]
    assert payload == {"offset": 5, "timeout": 0}


def test_token_never_appears_in_exception_message():
    client, _ = make_client([FakeResponse({"ok": False, "description": "unauthorized"})], token="TOP_SECRET")
    with pytest.raises(TelegramError) as excinfo:
        client.send_message("hi")
    assert "TOP_SECRET" not in str(excinfo.value)


def test_token_never_appears_in_ok_false_description_that_echoes_url():
    client, _ = make_client(
        [FakeResponse({"ok": False, "description": "bad request to https://api.telegram.org/botTOP_SECRET/sendMessage"})],
        token="TOP_SECRET",
    )
    with pytest.raises(TelegramError) as excinfo:
        client.send_message("hi")
    assert "TOP_SECRET" not in str(excinfo.value)


def test_token_never_appears_in_http_exception_message():
    import requests

    class LeakySession:
        def post(self, url, json, timeout):
            # requests/urllib3 embed the full request URL (with token) in real errors
            raise requests.ConnectionError(
                f"HTTPSConnectionPool(host='api.telegram.org', port=443): "
                f"Max retries exceeded with url: /botTOP_SECRET/sendMessage (Caused by ...)"
            )

    client = TelegramClient(token="TOP_SECRET", chat_id="123", http=LeakySession())
    with pytest.raises(TelegramError) as excinfo:
        client.send_message("hi")
    assert "TOP_SECRET" not in str(excinfo.value)
