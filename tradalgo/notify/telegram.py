import requests

API_ROOT = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


class TelegramClient:
    """Thin wrapper over the Telegram Bot HTTP API. Never logs the token."""

    def __init__(self, token: str, chat_id: str | int, http: requests.Session | None = None, timeout: int = 15):
        self._token = token
        self.chat_id = chat_id
        self.http = http if http is not None else requests.Session()
        self.timeout = timeout

    def _url(self, method: str) -> str:
        return API_ROOT.format(token=self._token, method=method)

    def _call(self, method: str, payload: dict) -> dict:
        try:
            resp = self.http.post(self._url(method), json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TelegramError(f"HTTP error calling {method}: {exc}") from None
        try:
            data = resp.json()
        except ValueError:
            raise TelegramError(f"non-JSON response from {method} (status {resp.status_code})") from None
        if not data.get("ok"):
            raise TelegramError(data.get("description", f"Telegram API error calling {method}"))
        return data["result"]

    @staticmethod
    def _keyboard(buttons: list[list[tuple[str, str]]] | None) -> dict | None:
        if not buttons:
            return None
        return {"inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row] for row in buttons
        ]}

    def send_message(self, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> int:
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        keyboard = self._keyboard(buttons)
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        result = self._call("sendMessage", payload)
        return result["message_id"]

    def edit_message(self, message_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> None:
        """buttons=None leaves the keyboard untouched; buttons=[] clears it."""
        payload = {"chat_id": self.chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
        if buttons is not None:
            payload["reply_markup"] = self._keyboard(buttons) or {"inline_keyboard": []}
        self._call("editMessageText", payload)

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    def get_updates(self, offset: int, timeout: int = 0) -> list[dict]:
        result = self._call("getUpdates", {"offset": offset, "timeout": timeout})
        return result
