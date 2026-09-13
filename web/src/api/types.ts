// Types mirror the B1 API contract exactly, per
// .superpowers/sdd/2026-09-14-tradalgo-v2/B1-report.md.

export interface HealthResponse {
  ok: boolean;
  db_path: string;
  market_open: boolean;
  trading_day: string | boolean;
  kill_switch: boolean;
  fyers_token_expiry: string | null;
}

export interface NowResponse {
  headline: string;
  quiet: boolean;
}

export interface ShortlistRow {
  rank: number;
  symbol: string;
  composite_score: number;
  factor_scores_json?: string;
  reasons?: string;
  gap_pct?: number;
  demoted?: boolean;
  [key: string]: unknown;
}

export interface SignalRow {
  signal_id: number;
  ts: string;
  symbol: string;
  strategy: string;
  direction: string;
  regime?: string;
  market_regime?: string;
  entry: number;
  stop_loss: number;
  target_2r?: number;
  target_3r?: number;
  features_json?: string;
  accepted: boolean;
  rejection_reason?: string | null;
  qty?: number;
  risk_rupees?: number;
  expected_value_r?: number;
  room_to_target_r?: number;
}

export interface Position {
  trade_id: number;
  signal_id: number;
  taken_by_user?: boolean;
  entry_ts: string;
  entry_price: number;
  qty: number;
  partial_exit_ts?: string | null;
  partial_exit_price?: number | null;
  exit_ts?: string | null;
  exit_price?: number | null;
  exit_reason?: string | null;
  mfe_r?: number;
  mae_r?: number;
  gross_r?: number;
  net_r?: number;
  symbol: string;
  strategy: string;
  direction: string;
  stop_loss: number;
  target_2r?: number;
  target_3r?: number;
  signal_ts?: string;
  user_action?: string;
  awaiting_reply: boolean;
}

export interface Alert {
  alert_id: number;
  dedup_key?: string;
  alert_type?: string;
  symbol: string;
  signal_id?: number;
  text: string;
  status: "sent" | "failed" | "awaiting" | string;
  created_at: string;
  sent_at?: string | null;
  latency_ms?: number | null;
  attempts?: number;
  last_error?: string | null;
  valid_until?: string | null;
  user_action?: string | null;
}

export interface AlertsResponse {
  alerts: Alert[];
  counts: { sent: number; failed: number; awaiting: number };
}

export interface JournalRow {
  signal_id: number;
  ts: string;
  symbol: string;
  strategy: string;
  direction: string;
  mode?: string;
  accepted?: boolean;
  rejection_reason?: string | null;
  entry_price?: number;
  exit_price?: number;
  exit_reason?: string;
  gross_r?: number;
  net_r?: number;
}

export interface AnalyticsGroupRow {
  grp: string;
  trades: number;
  win_rate: number;
  expectancy_r: number;
}

export interface MfeMaePoint {
  symbol: string;
  strategy: string;
  mfe_r: number;
  mae_r: number;
  net_r: number;
}

export interface LiveVsBacktestRow {
  strategy: string;
  live_expectancy_r: number;
  live_trades: number;
  backtest_expectancy_r: number;
  backtest_trades: number;
}

export interface AnalyticsResponse {
  expectancy_by_strategy: AnalyticsGroupRow[];
  expectancy_by_regime: AnalyticsGroupRow[];
  expectancy_by_hour: AnalyticsGroupRow[];
  expectancy_by_symbol: AnalyticsGroupRow[];
  mfe_mae_points: MfeMaePoint[];
  live_vs_backtest: LiveVsBacktestRow[];
}

export interface JobsResponse {
  job_runs: Record<string, unknown>[];
  health_events: Record<string, unknown>[];
  degraded_data: Record<string, unknown>[];
  degraded_socket: Record<string, unknown>[];
}

export type BacktestStatus = "queued" | "running" | "finished" | "failed" | "cancelled";

export interface BacktestParams {
  from: string;
  to: string;
  universe: "nifty50" | "niftynext50" | "both";
  strategies: string[];
  shortlist_size: number;
  slippage_pct: number;
  max_risk_pct: number;
  initial_capital: number;
}

export interface BacktestRun {
  id: number;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  status: BacktestStatus;
  params_json?: string;
  progress_pct?: number;
  metrics_json?: string;
  error?: string | null;
}

export interface BacktestMetrics {
  trades?: number;
  win_rate?: number;
  expectancy_r?: number;
  expectancy_r_no_slippage?: number;
  profit_factor?: number;
  max_drawdown_r?: number;
  net_r?: number;
  net_rupees?: number;
  missed_entries?: number;
  fill_rate?: number;
  by_strategy?: Record<string, unknown>;
  by_regime?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface GateVerdict {
  passed: boolean;
  reason: string;
}

export interface Diagnostics {
  by_hour?: Array<{ hour: number; trades: number; avg_r: number }>;
  by_exit_reason?: Array<{ reason: string; count: number; share: number }>;
  mfe_losers_by_strategy?: Record<string, number[]>;
  mfe_winners_stop_after_partial_by_strategy?: Record<string, number[]>;
  hard_exit_by_strategy?: Record<string, number>;
  fill_rate_by_strategy?: Record<string, number>;
  rejections?: Array<{ reason: string; count: number; rows?: unknown[] }>;
  [key: string]: unknown;
}

export interface BacktestDetailResponse {
  run: BacktestRun;
  params: BacktestParams | null;
  metrics: BacktestMetrics;
  gate: GateVerdict;
  diagnostics: Diagnostics | null;
}

export interface EquityPoint {
  trade_index: number;
  exit_ts: string;
  cum_net_r: number;
}

export interface RHistogramBin {
  bin_start: number;
  bin_end: number;
  count: number;
}

export interface LiveByStrategyRow {
  strategy: string;
  trades: number;
  win_rate: number;
  expectancy_r: number;
}

export interface BacktestLiveResponse {
  status: BacktestStatus;
  progress_pct: number;
  trades_so_far: number;
  win_rate: number;
  expectancy_r: number;
  net_r: number;
  max_drawdown_r: number;
  equity_curve: EquityPoint[];
  r_histogram: RHistogramBin[];
  by_strategy: LiveByStrategyRow[];
  latest_trades: Array<Record<string, unknown>>;
}

export interface Trade {
  id: string | number;
  signal_id?: number;
  trade_date: string;
  symbol: string;
  strategy: string;
  direction?: string;
  entry_ts?: string;
  entry_price: number;
  exit_ts?: string;
  exit_price?: number;
  exit_reason?: string;
  qty?: number;
  mfe_r?: number;
  mae_r?: number;
  gross_r?: number;
  net_r: number;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface VwapPoint {
  time: number;
  value: number;
}

export interface ReplayMarker {
  time: number;
  kind: "entry" | "partial_exit" | "stop_hit" | "runner_exit" | "hard_exit" | "trail_update";
  price: number;
  qty: number;
  r: number;
  new_stop?: number;
}

export interface StopPathPoint {
  time: number;
  value: number;
}

export interface ReplayResponse {
  trade: Trade;
  candles: Candle[];
  session_vwap: VwapPoint[];
  levels: {
    entry: number;
    stop: number;
    target_partial: number;
    target_runner: number;
  };
  markers: ReplayMarker[];
  stop_path?: StopPathPoint[];
}

export interface CandlesResponse {
  candles: Candle[];
  session_vwap?: VwapPoint[];
  levels?: Record<string, number>;
}

export interface SweepSummary {
  name: string;
  generated_at: string;
  verdict: string;
  total_combinations: number;
}

export interface SweepCombo {
  combo: string;
  train_r: number;
  test_r: number;
  delta: number;
  overfit: boolean;
}

export interface SweepDetailResponse {
  name?: string;
  generated_at: string;
  train?: { from: string; to: string };
  test?: { from: string; to: string };
  grid?: Record<string, unknown>;
  total_combinations: number;
  verdict: string;
  top?: SweepCombo[];
  combos: SweepCombo[];
  recommended_yaml?: string;
  [key: string]: unknown;
}

export interface Settings {
  [key: string]: unknown;
}

export interface ApiErrorBody {
  detail: string;
}
