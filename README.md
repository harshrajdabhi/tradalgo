# tradalgo

NSE intraday screener and alert system for Nifty 50 + Nifty Next 50. **Alerts only — it never places,
modifies or cancels orders.** You execute every trade by hand from the Telegram alert.

Strategy spec: `llm_intraday_stock_trading_spec.md`. Plan: `docs/superpowers/plans/2026-09-13-tradalgo-master.md`.

## Setup

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/tradalgo init          # creates data/tradalgo.db (SQLite, WAL mode)
.venv/bin/pytest
```

Tunable parameters (capital, risk, shortlist size, entry windows, screener/preopen/risk thresholds,
Telegram/dashboard settings) live in `config.yaml` and are validated on load.

## Secrets (macOS Keychain)

Secrets are stored via `keyring`, never in `.env` or files. Set each with:

```bash
.venv/bin/python -c "import keyring; keyring.set_password('tradalgo', '<NAME>', '<value>')"
```

Required names:

- `FYERS_APP_ID`, `FYERS_SECRET_KEY` — from your FYERS API app.
- `FYERS_PIN` — your FYERS trading PIN, used for the daily refresh-token → access-token exchange.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — your bot's token and the chat to alert.

The FYERS app's redirect URI must match `fyers.redirect_uri` in `config.yaml`.

## FYERS login

`fyers.login_with_auth_code` uses a browser once to get a refresh token valid for ~15 days:

```bash
.venv/bin/tradalgo login
```

Each morning the app exchanges the refresh token plus your PIN for a fresh access token — no browser
needed. Re-run `tradalgo login` roughly every 15 days when the refresh token expires (Telegram reminds
you 2 days out, once M9 ships).

## Backfill

```bash
.venv/bin/tradalgo backfill --months 12
```

Caches daily + 5-minute FYERS history for the Nifty 50 + Next 50 universe and the index to
`data/candles/*.parquet`.

## Per-symbol MIS leverage

FYERS' free API has no margin endpoint that doesn't also require the order/funds APIs, which this app
never touches. Fill in `data_static/mis_leverage.yaml` by hand from your broker's MIS margin sheet, one
`SYMBOL: leverage` entry per override. Anything not listed uses `capital.max_leverage`, and every value is
capped at `capital.max_leverage` regardless of what the file says.

## Daily flow

1. **07:00** `tradalgo screen` — ranks the universe on end-of-day data, saves the shortlist, sends the
   Telegram shortlist message. Safe to re-run; it skips a day that already succeeded unless `--force`.
2. **09:08** `tradalgo preopen` — annotates the shortlist with the actual pre-open gap and demotes picks
   where the gap has used up the expected move. Never adds new symbols. Skipped (with a warning) if FYERS
   quotes are unavailable — yfinance has no pre-open data.
3. **09:15–15:31** `tradalgo session` — the market-hours process: runs the shared engine cycle every 5
   minutes on today's shortlist, tracks open paper trades tick by tick, and queues entry/event/EOD alerts.
   Skips cleanly (exit 0) on a non-trading day or when today has no shortlist.
4. Always-on `tradalgo worker` — sends queued Telegram alerts (including the 07:00/09:08 shortlist), polls
   Telegram for Taken/Skipped button replies and `/status` requests, runs queued backtests, and once per
   day runs maintenance (FYERS token-expiry reminder, log rotation, old-data pruning). Independent of
   whether the session process is running. Stop it with Ctrl+C.
5. `tradalgo backtest --from YYYY-MM-DD --to YYYY-MM-DD [--universe both] [--strategies orb,gap,...] [--shortlist-size 6] [--slippage-pct X] [--max-risk-pct X] [--capital X]` —
   walk-forward replay of the same detectors/risk rules over cached candles. Prints trade count, win rate,
   expectancy (with and without slippage), profit factor, max drawdown, fill rate, missed entries, a
   by-strategy breakdown, and the M6 gate verdict. Fails with a `tradalgo backfill` hint if the candle
   cache doesn't cover the requested range.
6. `tradalgo report [--weeks N] [--run-id ID] [--telegram]` — prints the weekly performance report (taken
   vs not-taken, response rate, by-strategy expectancy) and a live-vs-backtest divergence check against the
   latest (or given) backtest run; `--telegram` also queues it for the worker to send.

**Verify the M6 backtest gate with `tradalgo backtest --from ... --to ...` before trusting live alerts.**

## Dashboard

```bash
.venv/bin/tradalgo dashboard
```

Opens Streamlit at `http://127.0.0.1:8501` (host/port from `config.yaml`, always loopback-only). It only
reads SQLite — it never calls FYERS directly or runs the trading engine.

## Scheduling with launchd

```bash
.venv/bin/tradalgo install-launchd --dry-run     # preview the rendered plists
.venv/bin/tradalgo install-launchd               # writes them to ~/Library/LaunchAgents
```

This prints the `launchctl bootstrap gui/$(id -u) <plist>` command for each job — it does not run
`launchctl` or `sudo` itself. launchd does **not** wake a sleeping Mac, so also schedule a wake before the
07:00 screener:

```bash
sudo pmset repeat wakeorpoweron MTWRF 06:55:00
```

## Before relying on live alerts

- Verify `data_static/nse_holidays_2026.yaml` (and the current year's file) against the official NSE
  holiday circular.
- **Do not trust live alerts until the M6 backtest gate is cleared**: expectancy must be > 0R after ₹50
  fixed cost and slippage, over at least 100 trades (`tradalgo backtest ...`). Otherwise tune thresholds
  or disable losing strategies in `config.yaml` and re-run.
- Run `tradalgo session` in shadow mode for a few days and check that every entry alert has a trigger,
  stop, 2R/3R target, qty, margin, invalidation price and valid-until time before treating it as
  actionable.
