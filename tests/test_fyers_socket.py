from datetime import datetime

from tradalgo.clock import IST, FixedClock
from tradalgo.data.fyers_socket import TickStream


class FakeSocket:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.subscribed, self.unsubscribed = [], []
        self.connected = self.closed = False
        FakeSocket.instances.append(self)

    def connect(self):
        self.connected = True
        self.kwargs["on_connect"]()

    def subscribe(self, symbols, data_type="SymbolUpdate"):
        self.subscribed.append((list(symbols), data_type))

    def unsubscribe(self, symbols, data_type="SymbolUpdate"):
        self.unsubscribed.append(list(symbols))

    def close_connection(self):
        self.closed = True


def make(ticks, statuses):
    clock = FixedClock(datetime(2026, 9, 15, 10, 0, tzinfo=IST))
    return TickStream("tok", "APP-100", lambda s, ts, ltp: ticks.append((s, ts, ltp)), statuses.append,
                      socket_cls=FakeSocket, clock=clock)


def test_subscribe_before_start_is_sent_on_connect_and_messages_map_to_ticks():
    ticks, statuses = [], []
    stream = make(ticks, statuses)
    stream.subscribe(["SBIN"])
    stream.start()
    sock = FakeSocket.instances[-1]
    assert sock.kwargs["access_token"] == "APP-100:tok"
    assert sock.subscribed == [(["NSE:SBIN-EQ"], "SymbolUpdate")]
    epoch = int(datetime(2026, 9, 15, 10, 1, 30, tzinfo=IST).timestamp())
    sock.kwargs["on_message"]({"symbol": "NSE:SBIN-EQ", "ltp": 812.5, "exch_feed_time": epoch, "type": "sf"})
    sock.kwargs["on_message"]({"symbol": "NSE:INFY-EQ", "ltp": 1500.0, "type": "sf"})
    sock.kwargs["on_message"]({"type": "sub", "code": 11011, "message": "Subscribed"})
    assert ticks == [("SBIN", datetime(2026, 9, 15, 10, 1, 30, tzinfo=IST), 812.5),
                     ("INFY", datetime(2026, 9, 15, 10, 0, tzinfo=IST), 1500.0)]
    assert ticks[0][1].tzinfo is not None


def test_unsubscribe_and_stop():
    stream = make([], statuses := [])
    stream.start()
    sock = FakeSocket.instances[-1]
    stream.subscribe(["SBIN", "INFY"])
    stream.subscribe(["SBIN"])
    stream.unsubscribe(["SBIN"])
    assert sock.subscribed == [(["NSE:INFY-EQ", "NSE:SBIN-EQ"], "SymbolUpdate")]
    assert sock.unsubscribed == [["NSE:SBIN-EQ"]]
    sock.kwargs["on_error"]({"code": -1})
    stream.stop()
    assert sock.closed and any("error" in s for s in statuses)


def test_stale_feed_time_falls_back_to_clock():
    ticks = []
    stream = make(ticks, [])
    stream.start()
    sock = FakeSocket.instances[-1]
    newer = int(datetime(2026, 9, 15, 9, 59, 50, tzinfo=IST).timestamp())
    sock.kwargs["on_message"]({"symbol": "NSE:SBIN-EQ", "ltp": 1.0, "exch_feed_time": newer})
    sock.kwargs["on_message"]({"symbol": "NSE:SBIN-EQ", "ltp": 2.0, "exch_feed_time": newer - 3600})
    assert ticks[1][1] == datetime(2026, 9, 15, 10, 0, tzinfo=IST)
