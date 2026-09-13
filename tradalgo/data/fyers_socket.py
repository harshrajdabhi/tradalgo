"""LTP ticks from the FYERS market-data websocket. Market data only: no order/position APIs."""
import tempfile
from datetime import datetime
from typing import Callable

from tradalgo.clock import IST, Clock, SystemClock
from tradalgo.data.fyers_provider import to_fyers_symbol


def from_fyers_symbol(fyers_symbol: str) -> str:
    name = fyers_symbol.split(":", 1)[-1]
    return "NIFTY50" if name == "NIFTY50-INDEX" else name.removesuffix("-EQ")


def _default_socket_cls():
    from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket
    return FyersDataSocket


class TickStream:
    def __init__(self, access_token: str, app_id: str,
                 on_tick: Callable[[str, datetime, float], None], on_status: Callable[[str], None],
                 socket_cls=None, clock: Clock | None = None, log_path: str | None = None):
        self._token = f"{app_id}:{access_token}"
        self._on_tick, self._on_status = on_tick, on_status
        self._socket_cls = socket_cls or _default_socket_cls()
        self._clock = clock or SystemClock()
        self._log_path = log_path or tempfile.gettempdir()
        self._symbols: set[str] = set()
        self._last_ts: dict[str, datetime] = {}
        self._socket = None
        self._connected = False

    def start(self) -> None:
        self._socket = self._socket_cls(
            access_token=self._token, write_to_file=False, log_path=self._log_path, litemode=False,
            reconnect=True, on_message=self._message, on_error=self._error, on_connect=self._connect,
            on_close=self._close,
        )
        self._socket.connect()

    def stop(self) -> None:
        if self._socket is not None:
            self._socket.close_connection()
        self._connected = False

    def subscribe(self, symbols) -> None:
        new = sorted(set(symbols) - self._symbols)
        self._symbols |= set(new)
        if new and self._connected:
            self._socket.subscribe([to_fyers_symbol(s) for s in new], data_type="SymbolUpdate")

    def unsubscribe(self, symbols) -> None:
        gone = sorted(set(symbols) & self._symbols)
        self._symbols -= set(gone)
        if gone and self._connected:
            self._socket.unsubscribe([to_fyers_symbol(s) for s in gone], data_type="SymbolUpdate")

    def _connect(self) -> None:
        self._connected = True
        self._on_status("connected")
        if self._symbols:
            self._socket.subscribe([to_fyers_symbol(s) for s in sorted(self._symbols)], data_type="SymbolUpdate")

    def _message(self, message) -> None:
        if not isinstance(message, dict) or "ltp" not in message or "symbol" not in message:
            return
        feed_time = message.get("exch_feed_time") or message.get("last_traded_time")
        symbol = from_fyers_symbol(message["symbol"])
        ts = datetime.fromtimestamp(int(feed_time), IST) if feed_time else self._clock.now()
        if symbol in self._last_ts and ts < self._last_ts[symbol]:
            ts = self._clock.now()  # a stale snapshot time (e.g. pre-open last_traded_time) must not rewind
        self._last_ts[symbol] = ts
        self._on_tick(symbol, ts, float(message["ltp"]))

    def _error(self, message) -> None:
        self._on_status(f"error: {message}")

    def _close(self, message) -> None:
        self._connected = False
        self._on_status(f"closed: {message}")
