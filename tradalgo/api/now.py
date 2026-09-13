"""Pure Now-strip priority logic, ported from tradalgo.dashboard.theme (which imports streamlit
at module scope and so cannot be imported from the API process).
"""
import re
from dataclasses import dataclass

_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(value: str) -> str:
    """Strip any HTML tags from DB-sourced text (alert bodies carry Telegram formatting tags)."""
    return _TAG_RE.sub("", value or "").strip()


@dataclass
class NowState:
    headline: str
    quiet: bool  # True once nothing needs action ("No action needed...")


def now_strip_state(*, kill_switch_on: bool, failed_alerts: list[dict],
                     awaiting_alerts: list[dict], open_trades: list[dict],
                     next_check: str) -> NowState:
    """Priority: kill switch on -> failed alerts -> entry alerts awaiting reply ->
    open taken trades -> nothing to do right now. All fields are plain text; the
    frontend is responsible for escaping when rendering as HTML.
    """
    if kill_switch_on:
        return NowState("Alerts are stopped. Resume alerts in the sidebar when you're ready.", quiet=False)

    if failed_alerts:
        a = failed_alerts[0]
        extra = f", and {len(failed_alerts) - 1} more" if len(failed_alerts) > 1 else ""
        last_error = _plain_text(a.get("last_error") or "unknown error")
        return NowState(f"Alert for {a['symbol']} failed to send ({last_error}){extra}. "
                         "Resend it from the Telegram page.", quiet=False)

    if awaiting_alerts:
        a = awaiting_alerts[0]
        extra = f", and {len(awaiting_alerts) - 1} more waiting" if len(awaiting_alerts) > 1 else ""
        text = _plain_text(a["text"])
        return NowState(
            f"{a['symbol']} alert is awaiting your reply: {text} (valid until {a['valid_until']}){extra}.",
            quiet=False,
        )

    if open_trades:
        t = open_trades[0]
        extra = f", and {len(open_trades) - 1} more open" if len(open_trades) > 1 else ""
        return NowState(f"{t['symbol']} is open from {t['entry_ts']} and still needs an exit{extra}.", quiet=False)

    return NowState(f"No action needed. Next check at {next_check}.", quiet=True)
