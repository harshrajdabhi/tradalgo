"""Pure plotly chart builders. No Streamlit or DB access here."""
import pandas as pd
import plotly.graph_objects as go

from tradalgo.dashboard import theme

_TEMPLATE = theme.plotly_template()


def _session_vwap(candles: pd.DataFrame) -> pd.Series:
    typical = (candles["high"] + candles["low"] + candles["close"]) / 3
    pv = typical * candles["volume"]
    cum_vol = candles["volume"].cumsum().replace(0, pd.NA)
    return (pv.cumsum() / cum_vol).astype(float)


def candlestick_with_levels(candles: pd.DataFrame, entry: float | None = None,
                             stop_loss: float | None = None, target_2r: float | None = None,
                             target_3r: float | None = None, title: str = "",
                             awaiting_reply: bool = False) -> go.Figure:
    """Draw the candles with entry/stop/2R/3R reference lines.

    Amber (theme.ACTION) is reserved for "needs your action": it is only used here when
    `awaiting_reply` is True, i.e. this signal's entry alert is still waiting on the user's
    reply. Otherwise the levels are quiet ink tones, distinguished by line style, not color.
    """
    fig = go.Figure()
    if not candles.empty:
        fig.add_trace(go.Candlestick(
            x=candles.index, open=candles["open"], high=candles["high"],
            low=candles["low"], close=candles["close"], name="price",
            increasing_line_color=theme.GAIN, decreasing_line_color=theme.LOSS,
        ))
        if candles["volume"].sum() > 0:
            fig.add_trace(go.Scatter(x=candles.index, y=_session_vwap(candles), name="VWAP",
                                      line=dict(color=theme.INK_MUTED)))
    primary = theme.ACTION if awaiting_reply else theme.INK
    secondary = theme.ACTION if awaiting_reply else theme.INK_MUTED
    for value, name, color, dash in (
        (entry, "entry", primary, "solid"), (stop_loss, "stop", primary, "dash"),
        (target_2r, "2R", secondary, "dot"), (target_3r, "3R", secondary, "dot"),
    ):
        if value is not None:
            fig.add_hline(y=value, line_dash=dash, line_color=color,
                          annotation_text=name, annotation_position="right")
    fig.update_layout(template=_TEMPLATE, title=title, xaxis_rangeslider_visible=False, height=450)
    return fig


def equity_curve(trades: pd.DataFrame, r_col: str = "net_r") -> go.Figure:
    fig = go.Figure()
    if not trades.empty:
        cum = trades[r_col].cumsum()
        fig.add_trace(go.Scatter(x=list(range(1, len(cum) + 1)), y=cum, mode="lines+markers",
                                 name="cumulative R", line=dict(color=theme.INK)))
    fig.update_layout(template=_TEMPLATE, title="Equity curve (cumulative R)",
                      xaxis_title="trade #", yaxis_title="R", height=350)
    return fig


def r_multiple_histogram(trades: pd.DataFrame, r_col: str = "net_r") -> go.Figure:
    fig = go.Figure()
    if not trades.empty:
        fig.add_trace(go.Histogram(x=trades[r_col], nbinsx=30, marker_color=theme.INK))
    fig.update_layout(template=_TEMPLATE, title="R-multiple distribution", xaxis_title="R", height=350)
    return fig


def mfe_mae_scatter(points: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not points.empty:
        fig.add_trace(go.Scatter(
            x=points["mae_r"], y=points["mfe_r"], mode="markers",
            marker=dict(color=points["net_r"], colorscale=[[0, theme.LOSS], [1, theme.GAIN]], showscale=True),
            text=points.get("symbol"),
        ))
    fig.update_layout(template=_TEMPLATE, title="MFE vs MAE", xaxis_title="MAE (R)", yaxis_title="MFE (R)",
                      height=400)
    return fig
