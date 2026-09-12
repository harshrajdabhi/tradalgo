# TradAlgo — NSE Intraday Alert System Implementation Plan (v2, revalidated)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan milestone-by-milestone. Before each milestone, run superpowers:writing-plans to expand that milestone into bite-sized TDD steps (tests + code) saved to `docs/superpowers/plans/2026-09-13-tradalgo-M<N>-<name>.md`. Use superpowers:test-driven-development for every task.

**Goal:** A local, mostly-free Python app that picks 5–7 intraday candidates from Nifty 50 + Nifty Next 50 before market open and sends Telegram entry/management alerts during the session using the strategy in `llm_intraday_stock_trading_spec.md`. It never places orders.

**Architecture:** Two jobs share one deterministic core. A 7:00 AM screener ranks the universe on end-of-day data. A market-hours process runs every 5 minutes, aligned to candle closes. It classifies the regime, runs the strategy detectors, validates each trade (sizing, room to target, expected value after costs) and sends alerts. The same `engine.cycle.run_cycle()` also drives the backtest and paper replay, so what gets validated is exactly what runs live.

**Tech Stack:** Python 3.11+, pandas/numpy, `pandas-ta`, `fyers-apiv3`, `yfinance` (fallback only), SQLite via SQLAlchemy Core, `APScheduler`, `requests` for the Telegram Bot API, `keyring` for secrets, `streamlit` + `plotly` for the local dashboard, `pytest`, launchd.

**Spec:** `/Users/harshrajdabhi/Documents/tradalgo/llm_intraday_stock_trading_spec.md`

## Context

The repo is empty apart from the spec. You chose:
- Alerts only.
- FYERS as the main data source, with yfinance as a fallback.
- A local Mac scheduled with launchd.
- Telegram for alerts.
- A configurable shortlist size, default 6.

This v2 revision rechecked v1 and fixes the issues below.

## What changed from v1 (revalidation findings)

| # | v1 issue | Fix in v2 |
|---|---|---|
| 1 | **Backtesting 6–12 months of 5-min data with yfinance is impossible.** yfinance only keeps about 60 days of 5-min history. | Get backtest history from the FYERS history API: 5-min candles in chunks of 100 days or less, cached locally as parquet in `data/candles/`. yfinance is for live fallback and quick dev checks only. |
| 2 | **Wrong claim that launchd wakes a sleeping Mac.** It doesn't. A missed `StartCalendarInterval` only runs after the Mac wakes. | Add `sudo pmset repeat wakeorpoweron MTWRF 06:55:00` to the setup docs. Every job also checks "already ran today?" so it's safe to run twice. |
| 3 | **A launchd `StartInterval: 300` poller isn't aligned to candle closes.** It could read a candle that is still forming (lookahead or repainting), and it keeps no memory between runs. | One market-session process started at 09:00 by launchd. Inside it, APScheduler runs a cron trigger at `minute=*/5, second=10` and only ever uses **closed** candles. It exits after 15:30. It keeps open-trade and regime state in memory and saves it to SQLite after each cycle so it can recover from a crash. |
| 4 | **FYERS login every morning by hand is fragile.** If you forget, the 7 AM job runs on degraded data. | FYERS v3 refresh-token flow: log in through the browser once, which gives a refresh token valid for about 15 days. Each morning the app gets a new access token from the refresh token plus your PIN, with no browser needed. The PIN and secrets are stored in macOS Keychain via `keyring`, not in a plaintext `.env`. Telegram reminds you 2 days before the refresh token expires. |
| 5 | **Between 5-min polls the app can't see SL or 2R hits, and a 5-min bar can hit both.** | Position monitoring uses the FYERS WebSocket (LTP) for shortlisted symbols with open alerts, so SL, 2R and trail alerts fire in near real time. In backtests, a bar that touches both SL and target counts as **SL first**, which is the conservative choice. |
| 6 | **The app doesn't know whether you actually took a trade**, so position-manager alerts and the daily trade cap could be wrong. | Two-way Telegram: every entry alert has `✅ Taken @price` / `❌ Skipped` inline buttons, handled by polling `getUpdates`. Taken trades get management alerts and count toward the cap and loss limit. Every alert, taken or not, is also paper-tracked so the model can be evaluated. |
| 7 | **No time-of-day rules.** Strategies were gated only by regime. | Each strategy gets an entry window. ORB: after the opening range (09:15–09:30), entries until 11:00. Gap setups: 09:20–10:15. Others: 09:30–14:00. **No new entries after 14:00**, because a realistic 2R needs time before the 15:00 hard exit. |
| 8 | **No market-level regime.** The spec says "market/stock regime". | The Nifty 50 index 5m/15m regime is classified too. Longs against a strong down-trending market are blocked, and vice versa, unless the strategy is marked counter-trend (VWAP rejection, gap-fade). |
| 9 | **Hard-coded 5× leverage.** MIS margin varies by stock and changes. | Per-symbol leverage comes from the FYERS margin data at 07:00, capped at `max_leverage: 5`. If the fetch fails, fall back to a conservative 3×. |
| 10 | **Liquidity and events were ignored.** Next 50 names can be thin, and results days are gap traps. | Hard filters before ranking: 20-day average turnover ≥ ₹50 cr, price ≥ ₹50, not in a results/board-meeting window (today or tomorrow, from NSE corporate-announcements data), and not in ASM/GSM. The "news/sentiment" factor starts as an **event blackout plus a Google News RSS keyword score**, defaulting to neutral. |
| 11 | **Hard-coded constituent list.** Indices rebalance twice a year. | `symbols.py` downloads the niftyindices.com constituent CSVs weekly and falls back to committed copies in `data_static/`. The NSE holiday list is a yearly YAML, and the app warns if the list for the current year is missing. |
| 12 | **A flat ₹50 cost hides slippage.** | The spec's ₹50 per completed trade is kept for net R. The backtest also adds slippage, configurable with a default of 0.05% per side. Metrics are reported both with and without slippage. |
| 13 | **Daily loss limit wasn't defined.** | Stop for the day after **−1R realized** on the first trade if the second setup isn't independent, or after **−2R total**. Kill switch: if the file `data/KILL` exists, or you send `/kill` in Telegram, all alerts stop. |
| 14 | **An alert with no expiry is dangerous** when you're entering by hand. | Every entry alert includes: trigger price, a limit band, an **invalidation price**, a **valid-until time** (next candle close), R:R, qty, margin needed, and a one-line reason. Expired alerts are edited in place to "EXPIRED". |
| 15 | **The 7 AM run can't see the gap.** | A second light pass at 09:08, after the NSE pre-open auction, attaches gap % to each pick and flags or demotes picks where a gap has already used up the expected move. It never adds new symbols. |
| 16 | **The plan wasn't split into testable units** as writing-plans requires. | Restructured below into 8 milestones. Each one ships working, tested software and gets its own detailed TDD sub-plan. |

## Global Constraints

- Never place, modify or cancel broker orders. The FYERS client wrapper exposes **only** data and market-data-socket methods, and a test checks that no order endpoints are imported.
- Capital ₹20,000. Max risk per trade 3% of current capital (₹600 initially). Max 2 trades per day. Max leverage 5×, used for sizing only. Qty = `min(floor(risk_rupees / |entry - SL|), floor(capital * leverage / entry))`. Fixed cost ₹50 per completed trade.
- Take a partial exit of 60% at 2R. Manage the other 40% as a runner. Hard exit at 15:00 IST. Never widen a stop or average down; no code path may produce either alert.
- Only accept a trade if the expected value after costs is > 0 and there is enough room to the next major level for 2R.
- All timestamps are timezone-aware `Asia/Kolkata`. Use only closed candles.
- Secrets live in macOS Keychain (`keyring`). `.env` holds only non-secret paths. Never commit `data/`, tokens or the DB.
- Every signal, feature, decision, alert, user response, paper fill, MFE/MAE, slippage and R outcome is logged to SQLite.
- Mostly free: no paid data vendors and no cloud infrastructure.
- The dashboard only reads SQLite. It never calls FYERS directly and never runs the trading engine inside the Streamlit process. It writes only through narrow "control" actions (kill switch file, backtest job request, config save with validation). Bind to `127.0.0.1` only.
- SQLite runs in WAL mode so the session process, backtest workers and dashboard can read and write at the same time.

## File Structure

```
tradalgo/
├── pyproject.toml, config.yaml, .env.example, .gitignore, README.md
├── data_static/                 # committed: nifty50.csv, niftynext50.csv, nse_holidays_2026.yaml
├── data/                        # gitignored: tradalgo.db, candles/*.parquet, logs/, KILL
├── tradalgo/
│   ├── config.py                # Settings dataclass (config.yaml + keyring secrets)
│   ├── clock.py                 # IST now(), market calendar, session windows (injectable for tests)
│   ├── data/
│   │   ├── base.py              # DataProvider protocol
│   │   ├── fyers_auth.py        # one-time browser login + daily refresh-token→access-token
│   │   ├── fyers_provider.py    # history, quotes, margins, pre-open (NO order methods)
│   │   ├── fyers_socket.py      # LTP websocket subscription for open positions
│   │   ├── yfinance_provider.py # fallback; marks data as degraded
│   │   ├── candle_cache.py      # parquet cache + chunked history backfill
│   │   └── universe.py          # constituents download/fallback, liquidity/event/ASM filters
│   ├── indicators/              # trend, volatility, volume, levels (PDH/PDL, swings, S/R, VWAP), momentum
│   ├── screener/
│   │   ├── factors.py           # 7 factor scorers, each -> 0..100
│   │   ├── events.py            # results/board-meeting blackout + RSS sentiment
│   │   ├── rank.py              # weighted composite, 2R-room reject, top-N
│   │   └── preopen.py           # 09:08 gap annotation/demotion
│   ├── regime.py                # classify(stock_5m, stock_15m, index_15m) -> Regime
│   ├── strategies/
│   │   ├── base.py              # Signal dataclass, Detector protocol, entry-window metadata
│   │   ├── orb.py, vwap.py, pdhl.py, pullback.py, range_breakout.py, gap.py
│   │   └── registry.py          # regime × time-window × market-alignment gating
│   ├── risk/
│   │   ├── sizing.py            # qty, leverage, margin required
│   │   ├── validator.py         # TradePlan | Rejection (room, EV, cap, loss limit, independence)
│   │   └── limits.py            # daily loss limit, kill switch
│   ├── engine/
│   │   ├── cycle.py             # run_cycle(ctx) — shared live/backtest core
│   │   ├── positions.py         # 2R partial, runner trail, 15:00 exit, SL-first rule
│   │   └── session.py           # live market-session process (APScheduler + socket + telegram listener)
│   ├── notify/
│   │   ├── telegram.py          # send/edit message, inline buttons, getUpdates listener, dedup
│   │   └── templates.py         # shortlist, entry, partial, trail, exit, expired, EOD summary, error
│   ├── storage/
│   │   ├── schema.py            # tables: job_runs, shortlist, signals, decisions, alerts, user_actions,
│   │   │                        #   paper_trades, backtest_runs, backtest_trades, health_events
│   │   └── repo.py              # thin typed insert/query helpers
│   ├── backtest/
│   │   ├── replay.py            # walk-forward day loop driving run_cycle bar-by-bar
│   │   ├── paper_broker.py      # fills, slippage, SL-first ambiguity, MFE/MAE
│   │   └── metrics.py           # expectancy (R), win rate, PF, max DD, per-strategy/regime breakdown
│   ├── jobs/
│   │   └── backtest_worker.py   # polls backtest_runs WHERE status='queued', runs replay, writes progress %
│   ├── dashboard/
│   │   ├── app.py               # Streamlit entry (st.navigation), sidebar: market status, kill switch, token expiry
│   │   ├── queries.py           # cached read-only SQL -> DataFrames (st.cache_data ttl=15s)
│   │   ├── charts.py            # plotly candlestick + VWAP/PDH/PDL + entry/SL/2R/3R markers, equity & R curves
│   │   └── pages/
│   │       ├── 1_today.py       # shortlist w/ factor scores, pre-open gaps, regime (stock+Nifty), live signals
│   │       ├── 2_positions.py   # taken/paper trades: live P&L in R & ₹, 2R/trail/exit state, per-trade chart
│   │       ├── 3_telegram.py    # alert delivery log: queued/sent/failed/retrying/edited/expired, attempts,
│   │       │                    #   last_error, latency, user action (Taken/Skipped/no reply); resend failed
│   │       ├── 4_backtest.py    # form (dates, universe, strategies, risk & slippage overrides) -> queue job;
│   │       │                    #   progress bar, run history, compare runs, metrics, equity curve, trades table
│   │       ├── 5_journal.py     # all trades & rejected signals w/ reasons, filters, CSV export, notes field
│   │       ├── 6_analytics.py   # expectancy by strategy/regime/time-of-day/symbol, MFE/MAE scatter,
│   │       │                    #   live-vs-backtest divergence
│   │       ├── 7_health.py      # job_runs (screen/preopen/session heartbeat), provider status & DEGRADED periods,
│   │       │                    #   FYERS token expiry, websocket status, error log
│   │       └── 8_settings.py    # view/edit config.yaml (pydantic-validated, backup on save), strategy enable toggles
│   └── cli.py                   # `tradalgo login | screen | preopen | session | backtest | worker | dashboard | report`
├── launchd/                     # com.tradalgo.screen.plist (07:00), .preopen (09:08), .session (09:00),
│                                #   .worker (KeepAlive), .dashboard (KeepAlive, localhost:8501)
└── tests/                       # mirrors tradalgo/ ; fixtures: synthetic candle builders, fake clock, fake provider
```

## Milestones (each gets its own detailed TDD sub-plan)

### M1: Foundation, config and storage
Build `pyproject.toml`, `config.py` (YAML + keyring), `clock.py` (IST, holidays, session windows), `storage/schema.py` and `repo.py`, and a `cli.py` skeleton.
**Deliverable:** `tradalgo init` creates the DB, and `pytest` passes for calendar edge cases (holidays, weekends, 15:00/15:30 boundaries).

### M2: Data layer
Build the `DataProvider` protocol, FYERS auth (browser login + refresh-token flow), `fyers_provider` (history, quotes, margins, pre-open; no order methods), the yfinance fallback with a degraded flag, the parquet `candle_cache` with chunked backfill, and `universe.py` with filters.
**Deliverable:** `tradalgo backfill --months 12` fills 5-min and daily history for about 100 symbols plus the index. Tests use a fake provider. A contract test checks that both providers return identical schemas. A test asserts no order endpoints are imported.

### M3: Indicators and screener
Build the indicators, the 7 factors, the event blackout, `rank.py` with the 2R-room reject, and `preopen.py`.
**Deliverable:** `tradalgo screen --date 2026-09-11` prints and saves a ranked shortlist with per-factor reasons. Tests use synthetic candles with known ATR, VWAP and ADX values.

### M4: Regime and the 6 strategy detectors
Build `regime.py` (stock + index), each detector with entry-window metadata, and `registry.py` gating.
**Deliverable:** each detector has trigger and no-trigger fixture tests, plus a check that entry, SL and targets match hand-calculated values. Registry tests check time-window and market-alignment gating.

### M5: Risk and position management (pure math)
Build `sizing.py`, `validator.py`, `limits.py` and `engine/positions.py`.
**Deliverable:** table-driven tests for qty = min(risk, leverage), EV sign, room rejection, 2-trade cap, second-trade independence, −2R limit, kill switch, the 2R partial (fires once), trail advancing only in the favorable direction, the 15:00 exit, and SL-first handling for ambiguous bars.

### M6: Backtest and paper (the safety gate)
Build `engine/cycle.py`, `backtest/replay.py` (walk-forward: re-screen each day on data available up to that day), `paper_broker.py` and `metrics.py`.
**Deliverable:** `tradalgo backtest --from 2025-09-01 --to 2026-08-31` produces a metrics report by strategy and regime. A smoke test covers a 1-week fixture. A lookahead test checks that shifting future candles never changes past decisions.
**Gate:** don't start M7 until expectancy is > 0 R after ₹50 cost and slippage, with at least 100 trades. Otherwise tune thresholds or disable losing strategies in `config.yaml`, and re-run.

### M7: Live session and Telegram
Build `notify/telegram.py` (send/edit, inline Taken/Skipped buttons, `/kill`, `/status`), templates, `engine/session.py` (APScheduler cron at `*/5` minutes and second 10, FYERS socket for open positions, crash recovery from SQLite), and launchd plists plus `pmset` setup docs.
**Deliverable:** a shadow run against a replayed day using the fake clock and fake socket, checking the exact sequence of alerts. Then run 5 live sessions to a test chat before trusting it.

### M8: Streamlit dashboard
Build `dashboard/` (the 8 pages above), `jobs/backtest_worker.py`, and the dashboard and worker launchd plists.
- **Telegram status tracking:** `notify/telegram.py` writes every message to `alerts` *before* sending (`status=queued`). It then updates the row to `sent` (with `message_id`, `sent_at`, latency) or `failed` (with `attempts`, `last_error`), and later to `edited`/`expired`. Button presses write to `user_actions`. The Telegram page's "Resend" button only sets `status=queued`. A sender loop in the always-on worker process picks it up, so resends and 07:00 shortlist messages go out even when the market session process isn't running. This keeps a single sender and preserves dedup.
- **Backtest from the UI:** the form inserts a `backtest_runs` row (params JSON, `status=queued`). The worker process runs it, updates `progress_pct`/`status`, and writes results to `backtest_trades`. The page auto-refreshes with `st.fragment(run_every=3)`. Long runs never block or die with the Streamlit session. A "Cancel" button sets `status=cancel_requested`, which the worker checks between trading days.
- **Controls:** the sidebar kill switch creates or removes `data/KILL`, and the session process checks it every cycle. Settings saves are validated by the same pydantic model `config.py` uses, a timestamped backup is written, and the session process reloads config at the next cycle.
- **Live refresh:** the Today and Positions pages refresh with `st.fragment(run_every=15)` during market hours, reading only from SQLite.
**Deliverable:** `tradalgo dashboard` opens at `http://127.0.0.1:8501`. Tests: `queries.py` against a seeded fixture DB; Streamlit `AppTest` smoke tests that each page renders with an empty DB and with a seeded DB; worker tests for queued → running → done / failed / cancelled; a Telegram-status test with a fake HTTP client for send success, 3 retries then failure, and resend.

### M9: Hardening and reporting
Add: an EOD Telegram summary; `tradalgo report` (weekly R curve, live-vs-paper divergence); a provider-failure alert with automatic yfinance fallback (alerts marked DEGRADED); a token-expiry reminder; and log rotation.
**Deliverable:** fault-injection tests for FYERS down, Telegram down (queue and retry) and token expiry.

### Future (not in scope)
A meta-model estimating P(2R before SL) trained on logged `signals` and `paper_trades`; a read-only dashboard.

## Verification (end-to-end)

1. `pytest` passes, including the lookahead test and the no-order-endpoint test.
2. `tradalgo backfill --months 12`, then `tradalgo backtest ...`, clears the M6 gate. Review the report by hand.
3. `tradalgo screen` on a real morning: a Telegram shortlist arrives with reasons. `tradalgo preopen` at 09:08 adds gap notes.
4. Shadow-mode `tradalgo session` for 5 trading days: every entry alert has trigger, SL, 2R/3R, qty, margin, invalidation and valid-until. Taken/Skipped buttons are logged. No duplicate alerts. The 15:00 exit alert fires for taken runners. The EOD summary matches the DB.
5. Dashboard: start a 1-month backtest from the Backtest page. The progress bar advances and the metrics and equity curve appear when it finishes. Kill Telegram connectivity (bad token in a test profile): the alerts show `failed` with the error on the Telegram page, and "Resend" works once the token is fixed. Toggle the kill switch in the sidebar and confirm the session log shows alerts suppressed. The Health page shows the last run for each job and the token expiry.

## Housekeeping
- After approval, copy this plan to `docs/superpowers/plans/2026-09-13-tradalgo-master.md`.
- Record the key decisions (alerts-only, FYERS refresh-token + Keychain, single session process, SL-first backtest rule, M6 gate) in the Obsidian vault under `Decisions/` and `Context/tradalgo.md`.
