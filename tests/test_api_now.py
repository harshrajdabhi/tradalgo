from tradalgo.api.now import now_strip_state


def _state(**kw):
    base = dict(kill_switch_on=False, failed_alerts=[], awaiting_alerts=[], open_trades=[], next_check="10:00")
    return now_strip_state(**{**base, **kw})


def test_now_strip_priority():
    failed = [{"symbol": "X", "last_error": "timeout"}]
    awaiting = [{"symbol": "Y", "text": "buy Y", "valid_until": "10:30"}]
    opened = [{"symbol": "Z", "entry_ts": "09:20"}]

    s = _state(kill_switch_on=True, failed_alerts=failed, awaiting_alerts=awaiting, open_trades=opened)
    assert "Resume alerts" in s.headline and not s.quiet

    s = _state(failed_alerts=failed, awaiting_alerts=awaiting, open_trades=opened)
    assert "X" in s.headline and "timeout" in s.headline and not s.quiet

    s = _state(awaiting_alerts=awaiting, open_trades=opened)
    assert "Y" in s.headline and "10:30" in s.headline and not s.quiet

    s = _state(open_trades=opened)
    assert "Z" in s.headline and not s.quiet

    s = _state()
    assert "10:00" in s.headline and s.quiet


def test_now_strip_strips_markup_from_db_text():
    s = _state(failed_alerts=[{"symbol": "X", "last_error": "<script>alert(1)</script> timeout"}])
    assert "<script>" not in s.headline and "timeout" in s.headline

    s = _state(awaiting_alerts=[{"symbol": "Y", "text": "<b>Buy</b> RELIANCE", "valid_until": "10:30"}])
    assert "<b>" not in s.headline and "Buy RELIANCE" in s.headline
