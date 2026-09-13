"""Visual identity tokens: colors, the CSS injection helper, the plotly template,
and the pure "Now" strip priority logic. No data queries here.
"""
import html as _html
import re
from dataclasses import dataclass

import plotly.graph_objects as go
import streamlit as st

# Named tokens. Cool neutral paper desk, not the near-black/neon default trading-app look.
# Contrast ratios below are computed against the WCAG relative-luminance formula;
# see dashboard-design-report.md "Fix round 1" for the full table.
PAPER = "#EEF1F4"        # page background: a genuinely cool blue-grey, not warm cream
PANEL = "#E4E8EC"        # secondary background (sidebar etc.), a slightly darker cool tone of PAPER
INK = "#16233D"          # primary text, deep navy — 13.8:1 on PAPER
INK_MUTED = "#55617A"    # secondary text / axis labels — 5.49:1 on PAPER (passes AA text 4.5:1)
LINE = "#D8D9D3"         # hairline borders, dividers, muted grid (decorative, not text)
GAIN = "#2F6D4F"         # muted green, ONLY for P&L/R numbers that are positive — 5.41:1 on PAPER
LOSS = "#8C3B34"         # muted red, ONLY for P&L/R numbers that are negative — 6.64:1 on PAPER
ACTION = "#B4750F"       # amber, ONLY for "needs your action" states — 3.37:1 on PAPER (UI/stroke use only, never body text)

_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(value: str) -> str:
    """Strip any HTML tags from DB-sourced text (alert bodies carry Telegram formatting tags)."""
    return _TAG_RE.sub("", value or "").strip()

FONT_STACK = '"Public Sans", -apple-system, "Segoe UI", sans-serif'

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: {FONT_STACK};
}}

/* Tabular figures for prices and R values wherever numbers line up */
[data-testid="stMetricValue"], [data-testid="stDataFrame"], table, .stDataFrame {{
    font-variant-numeric: tabular-nums;
}}

.now-strip {{
    border: 1px solid {LINE};
    border-left: 4px solid {ACTION};
    border-radius: 4px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 1.2rem;
    background: #FFFFFF;
    color: {INK};
    font-size: 1.05rem;
}}
.now-strip.now-strip--quiet {{
    border-left-color: {LINE};
    color: {INK_MUTED};
}}

/* Keep a visible focus ring rather than relying on the browser default alone */
button:focus-visible, [tabindex]:focus-visible, input:focus-visible {{
    outline: 2px solid {INK} !important;
    outline-offset: 2px;
}}
</style>
"""


def inject_css() -> None:
    """Call once per page to apply the shared visual identity."""
    st.markdown(_CSS, unsafe_allow_html=True)


def plotly_template() -> go.layout.Template:
    return go.layout.Template(
        layout=go.Layout(
            paper_bgcolor=PAPER,
            plot_bgcolor=PAPER,
            font=dict(family=FONT_STACK, color=INK),
            xaxis=dict(gridcolor=LINE, linecolor=LINE, zerolinecolor=LINE, color=INK_MUTED),
            yaxis=dict(gridcolor=LINE, linecolor=LINE, zerolinecolor=LINE, color=INK_MUTED),
            colorway=[INK, GAIN, LOSS, ACTION, INK_MUTED],
        )
    )


@dataclass
class NowState:
    headline: str
    quiet: bool  # True once nothing needs action ("No action needed...")


def now_strip_state(*, kill_switch_on: bool, failed_alerts: list[dict],
                     awaiting_alerts: list[dict], open_trades: list[dict],
                     next_check: str) -> NowState:
    """Pure priority logic for the Today page's "Now" strip.

    Priority: kill switch on -> failed alerts -> entry alerts awaiting reply ->
    open taken trades -> nothing to do right now.
    Each list item is a plain dict already read from the DB by the caller.
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


def render_now_strip_html(state: NowState) -> str:
    """Build the Now strip's HTML, escaping the dynamic headline so DB-sourced text
    (alert bodies, Telegram error messages) can never inject markup. Only the static
    wrapper markup is unescaped; the content is always html.escape()'d text.
    """
    css_class = "now-strip now-strip--quiet" if state.quiet else "now-strip"
    safe_headline = _html.escape(state.headline)
    return f'<div class="{css_class}">{safe_headline}</div>'
