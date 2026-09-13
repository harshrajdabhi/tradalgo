import type * as T from "../api/types";

export const health: T.HealthResponse = {
  ok: true,
  db_path: "/data/tradalgo.db",
  market_open: true,
  trading_day: "2026-09-14",
  kill_switch: false,
  fyers_token_expiry: "2026-09-15",
};

export const now: T.NowResponse = {
  headline: "RELIANCE alert failed to send (timeout). Resend it from Alerts.",
  quiet: false,
};

export const nowQuiet: T.NowResponse = {
  headline: "No action needed. Next check at 09:56.",
  quiet: true,
};

export const shortlist: T.ShortlistRow[] = [
  { rank: 1, symbol: "RELIANCE", composite_score: 78, reasons: "trending, strong ORB", gap_pct: 0.4, demoted: false },
  { rank: 2, symbol: "TCS", composite_score: 61, reasons: "range, VWAP reversion", gap_pct: -0.1, demoted: false },
  { rank: 3, symbol: "INFY", composite_score: 55, reasons: "trending", gap_pct: 0.2, demoted: false },
  { rank: 4, symbol: "HDFCBANK", composite_score: 49, reasons: "range", gap_pct: 0.0, demoted: false },
  { rank: 5, symbol: "ICICIBANK", composite_score: 44, reasons: "choppy", gap_pct: -0.3, demoted: true },
];

export const signals: T.SignalRow[] = [
  { signal_id: 1, ts: "2026-09-14T09:41:00Z", symbol: "RELIANCE", strategy: "orb", direction: "long", entry: 2845.1, stop_loss: 2822, accepted: true },
  { signal_id: 2, ts: "2026-09-14T09:38:00Z", symbol: "TCS", strategy: "vwap-rev", direction: "long", entry: 3910, stop_loss: 3880, accepted: false, rejection_reason: "spread too wide" },
  { signal_id: 3, ts: "2026-09-14T09:22:00Z", symbol: "INFY", strategy: "orb", direction: "long", entry: 1550, stop_loss: 1535, accepted: true },
  { signal_id: 4, ts: "2026-09-14T09:10:00Z", symbol: "HDFCBANK", strategy: "orb", direction: "long", entry: 1650, stop_loss: 1635, accepted: false, rejection_reason: "regime mismatch" },
];

export const positions: T.Position[] = [
  {
    trade_id: 1,
    signal_id: 1,
    entry_ts: "2026-09-14T09:20:00Z",
    entry_price: 2845.1,
    qty: 40,
    stop_loss: 2822,
    symbol: "RELIANCE",
    strategy: "orb",
    direction: "long",
    awaiting_reply: false,
  },
  {
    trade_id: 2,
    signal_id: 3,
    entry_ts: "2026-09-14T09:25:00Z",
    entry_price: 3910.0,
    qty: 25,
    stop_loss: 3940,
    symbol: "TCS",
    strategy: "vwap-rev",
    direction: "short",
    awaiting_reply: false,
  },
];

export const alerts: T.AlertsResponse = {
  alerts: [
    { alert_id: 1, symbol: "RELIANCE", text: "entry alert", status: "failed", created_at: "2026-09-14T09:41:00Z", last_error: "Telegram timed out" },
    { alert_id: 2, symbol: "TCS", text: "skip notice", status: "sent", created_at: "2026-09-14T09:38:00Z" },
    { alert_id: 3, symbol: "INFY", text: "entry alert — awaiting reply", status: "awaiting", created_at: "2026-09-14T09:22:00Z" },
    { alert_id: 4, symbol: "HDFCBANK", text: "skip notice", status: "sent", created_at: "2026-09-14T09:10:00Z" },
  ],
  counts: { sent: 2, failed: 1, awaiting: 1 },
};

export const journal: T.JournalRow[] = [
  { signal_id: 1, ts: "2026-09-10T09:20:00Z", symbol: "RELIANCE", strategy: "orb", direction: "long", exit_reason: "target", net_r: 1.2 },
  { signal_id: 2, ts: "2026-09-10T10:05:00Z", symbol: "TCS", strategy: "vwap-rev", direction: "short", exit_reason: "stop", net_r: -1.0 },
  { signal_id: 3, ts: "2026-09-11T09:40:00Z", symbol: "INFY", strategy: "orb", direction: "long", exit_reason: "eod", net_r: 0.4 },
];

export const analytics: T.AnalyticsResponse = {
  expectancy_by_strategy: [
    { grp: "orb", trades: 140, win_rate: 0.55, expectancy_r: 0.22 },
    { grp: "vwap-rev", trades: 96, win_rate: 0.48, expectancy_r: -0.05 },
  ],
  expectancy_by_regime: [
    { grp: "trending", trades: 120, win_rate: 0.6, expectancy_r: 0.3 },
    { grp: "range", trades: 80, win_rate: 0.45, expectancy_r: -0.1 },
    { grp: "choppy", trades: 36, win_rate: 0.4, expectancy_r: -0.2 },
  ],
  expectancy_by_hour: [
    { grp: "9", trades: 60, win_rate: 0.6, expectancy_r: 0.4 },
    { grp: "10", trades: 55, win_rate: 0.52, expectancy_r: 0.1 },
    { grp: "11", trades: 40, win_rate: 0.45, expectancy_r: -0.05 },
    { grp: "14", trades: 30, win_rate: 0.5, expectancy_r: 0.2 },
  ],
  expectancy_by_symbol: [
    { grp: "RELIANCE", trades: 30, win_rate: 0.6, expectancy_r: 0.5 },
    { grp: "TCS", trades: 28, win_rate: 0.45, expectancy_r: -0.1 },
  ],
  mfe_mae_points: [
    { symbol: "RELIANCE", strategy: "orb", mfe_r: 1.8, mae_r: -0.3, net_r: 1.2 },
    { symbol: "TCS", strategy: "vwap-rev", mfe_r: 0.4, mae_r: -1.0, net_r: -1.0 },
  ],
  live_vs_backtest: [
    { strategy: "orb", live_expectancy_r: 0.15, live_trades: 40, backtest_expectancy_r: 0.22, backtest_trades: 140 },
    { strategy: "vwap-rev", live_expectancy_r: -0.1, live_trades: 20, backtest_expectancy_r: -0.05, backtest_trades: 96 },
  ],
};

export const jobs: T.JobsResponse = {
  job_runs: [
    { id: 1, name: "eod_scan", started_at: "2026-09-13T18:00:00Z", finished_at: "2026-09-13T18:02:00Z", status: "ok" },
    { id: 2, name: "token_refresh", started_at: "2026-09-14T02:00:00Z", finished_at: "2026-09-14T02:00:05Z", status: "ok" },
  ],
  health_events: [{ time: "2026-09-13T18:02:01Z", kind: "info", message: "eod_scan completed" }],
  degraded_data: [],
  degraded_socket: [],
};

const equityCurveRunning: T.EquityPoint[] = Array.from({ length: 37 }, (_, i) => ({
  trade_index: i + 1,
  exit_ts: `2026-09-14T0${9 + Math.floor(i / 10)}:${(i % 60).toString().padStart(2, "0")}:00Z`,
  cum_net_r: Number((Math.sin(i / 5) * 2 + i * 0.15).toFixed(2)),
}));

export const backtestRuns: T.BacktestRun[] = [
  {
    id: 142,
    created_at: "2026-09-14T09:00:00Z",
    status: "running",
    progress_pct: 62,
    params_json: JSON.stringify({ from: "2026-03-01", to: "2026-09-11", universe: "nifty50", strategies: ["orb", "vwap-rev"] }),
  },
  {
    id: 141,
    created_at: "2026-09-13T09:00:00Z",
    status: "finished",
    progress_pct: 100,
    params_json: JSON.stringify({ from: "2026-01-01", to: "2026-06-30", universe: "both", strategies: ["orb"] }),
    metrics_json: JSON.stringify({ net_r: 6.2 }),
  },
];

export const backtestLive: T.BacktestLiveResponse = {
  status: "running",
  progress_pct: 62,
  trades_so_far: 37,
  win_rate: 0.54,
  expectancy_r: 0.18,
  net_r: 6.2,
  max_drawdown_r: -2.1,
  equity_curve: equityCurveRunning,
  r_histogram: [
    { bin_start: -2, bin_end: -1, count: 3 },
    { bin_start: -1, bin_end: 0, count: 8 },
    { bin_start: 0, bin_end: 1, count: 2 },
    { bin_start: 1, bin_end: 2, count: 14 },
    { bin_start: 2, bin_end: 3, count: 7 },
    { bin_start: 3, bin_end: 4, count: 3 },
  ],
  by_strategy: [
    { strategy: "orb", trades: 14, win_rate: 0.6, expectancy_r: 0.22 },
    { strategy: "vwap-rev", trades: 11, win_rate: 0.4, expectancy_r: -0.05 },
  ],
  latest_trades: [
    { time: "09:41", symbol: "RELIANCE", net_r: 1.2 },
    { time: "09:22", symbol: "TCS", net_r: -1.0 },
    { time: "09:05", symbol: "INFY", net_r: 0.4 },
  ],
};

export const backtestDetailFinished: T.BacktestDetailResponse = {
  run: backtestRuns[1],
  params: {
    from: "2026-01-01",
    to: "2026-06-30",
    universe: "both",
    strategies: ["orb"],
    shortlist_size: 6,
    slippage_pct: 0.05,
    max_risk_pct: 0.01,
    initial_capital: 500000,
  },
  metrics: {
    trades: 62,
    win_rate: 0.51,
    expectancy_r: 0.1,
    expectancy_r_no_slippage: 0.14,
    profit_factor: 1.2,
    max_drawdown_r: -4.5,
    net_r: 6.2,
    net_rupees: 62000,
    missed_entries: 5,
    fill_rate: 0.92,
  },
  gate: { passed: false, reason: "62 trades (need 100)" },
  diagnostics: {
    by_hour: [
      { hour: 9, trades: 20, avg_r: 0.3 },
      { hour: 10, trades: 18, avg_r: 0.1 },
      { hour: 11, trades: 12, avg_r: -0.1 },
      { hour: 14, trades: 12, avg_r: 0.05 },
    ],
    by_exit_reason: [
      { reason: "target", count: 22, share: 0.35 },
      { reason: "stop", count: 20, share: 0.32 },
      { reason: "trail", count: 12, share: 0.19 },
      { reason: "eod", count: 8, share: 0.14 },
    ],
    mfe_losers_by_strategy: { orb: [0.2, 0.4, 0.1, 0.6, 0.3] },
    mfe_winners_stop_after_partial_by_strategy: { orb: [1.1, 1.4, 0.9] },
    hard_exit_by_strategy: { orb: 4 },
    fill_rate_by_strategy: { orb: 0.92 },
    rejections: [
      { reason: "spread too wide", count: 6 },
      { reason: "no liquidity", count: 2 },
    ],
  },
};

export const backtestTrades: T.Trade[] = [
  { id: "t1", trade_date: "2026-08-14", symbol: "RELIANCE", strategy: "orb", entry_price: 2845.1, exit_reason: "target", net_r: 1.2 },
  { id: "t2", trade_date: "2026-08-14", symbol: "TCS", strategy: "vwap-rev", entry_price: 3910, exit_reason: "stop", net_r: -1.0 },
  { id: "t3", trade_date: "2026-08-15", symbol: "INFY", strategy: "orb", entry_price: 1550, exit_reason: "eod", net_r: 0.4 },
];

function buildReplayCandles(): T.Candle[] {
  const start = Date.UTC(2026, 7, 14, 3, 45); // 09:15 IST in UTC
  const candles: T.Candle[] = [];
  let price = 2845;
  for (let i = 0; i < 75; i++) {
    const open = price;
    const drift = Math.sin(i / 8) * 3 + (i > 40 ? -0.4 : 0.3);
    const close = open + drift + (Math.random() - 0.5) * 2;
    const high = Math.max(open, close) + Math.random() * 2;
    const low = Math.min(open, close) - Math.random() * 2;
    candles.push({
      time: Math.floor(start / 1000) + i * 300,
      open: Number(open.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      close: Number(close.toFixed(2)),
      volume: Math.floor(1000 + Math.random() * 4000),
    });
    price = close;
  }
  return candles;
}

const replayCandles = buildReplayCandles();

export const replay: T.ReplayResponse = {
  trade: backtestTrades[0],
  candles: replayCandles,
  session_vwap: replayCandles.map((c, i) => ({ time: c.time, value: Number((2840 + i * 0.3).toFixed(2)) })),
  levels: { entry: 2845.1, stop: 2822, target_partial: 2880, target_runner: 2920 },
  markers: [
    { time: replayCandles[5].time, kind: "entry", price: 2845.1, qty: 40, r: 0 },
    { time: replayCandles[25].time, kind: "partial_exit", price: 2880, qty: 20, r: 1.0 },
    { time: replayCandles[30].time, kind: "trail_update", price: 2855, qty: 20, r: 0.5, new_stop: 2855 },
    { time: replayCandles[55].time, kind: "runner_exit", price: 2870, qty: 20, r: 0.7 },
  ],
  stop_path: [
    { time: replayCandles[5].time, value: 2822 },
    { time: replayCandles[30].time, value: 2855 },
  ],
};

export const sweeps: T.SweepSummary[] = [
  { name: "sweep-2026-09-10", generated_at: "2026-09-10T00:00:00Z", verdict: "mixed", total_combinations: 3 },
];

export const sweepDetail: T.SweepDetailResponse = {
  generated_at: "2026-09-10T00:00:00Z",
  train: { from: "2026-01-01", to: "2026-04-30" },
  test: { from: "2026-05-01", to: "2026-06-30" },
  grid: { stop_mult: [0.5, 1, 1.5] },
  total_combinations: 3,
  verdict: "one combo flagged overfit",
  combos: [
    { combo: "orb·tight-stop", train_r: 8.2, test_r: 1.1, delta: -7.1, overfit: true },
    { combo: "orb·wide-stop", train_r: 5.4, test_r: 4.9, delta: -0.5, overfit: false },
    { combo: "vwap-rev·std", train_r: 6.0, test_r: 5.8, delta: -0.2, overfit: false },
  ],
  recommended_yaml: "strategy: orb\nstop_mult: 1.0\nshortlist_size: 6\n",
};

export const settings: T.Settings = {
  max_risk_pct: 0.01,
  shortlist_size: 6,
  slippage_pct: 0.05,
  kill_switch: false,
};
