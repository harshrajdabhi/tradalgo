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
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — your bot's token and the chat to alert. `TELEGRAM_CHAT_ID`
  may be a comma-separated list (`111,222`) to mirror alerts to more than one chat; only the first one
  gets Taken/Skipped buttons and later edits (expiry, "marked TAKEN"), the rest get a read-only copy.
  A command reply (`/kill`, `/status`, ...) from any listed chat is honored.

The FYERS app's redirect URI must match `fyers.redirect_uri` in `config.yaml`.

**Create the FYERS API app as "Non-trading"** (or, if using a "Trading" app, never grant it "Order
placements"). This app only ever reads history/quotes — a credential that has no order-placement
permission at all is a second line of defense, on top of the code-level guard, in case of a bug or a
mistaken manual call. A Non-trading app also has no IP-address restriction, unlike a Trading app —
important if any part of this ever runs on GitHub Actions, where the runner's IP changes every run.

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
   Add `--test` to try it on a weekend/holiday: instead of skipping, it screens using the last actual
   trading day's data (no Telegram alert is sent, so it never spams your chat with a stale shortlist).
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

## Running locally

```bash
cp .env.example .env      # fill in your real values; .env is gitignored
scripts/run_local.sh      # worker + dashboard + the live session, until Ctrl+C
```

`scripts/run_local.sh` exports everything in `.env` before running, and `KeyringStore` checks the
environment before Keychain — so filling in `.env` is enough locally, no `keyring.set_password` calls
needed (though Keychain still works if you prefer it, e.g. for a launchd-scheduled run with no shell to
source `.env` into). Other modes: `scripts/run_local.sh screen`, `scripts/run_local.sh preopen`,
`scripts/run_local.sh session-only`.

## Paper-testing on GitHub Actions (no Mac required)

Two workflows in `.github/workflows/` run the morning screener and the intraday cycle on GitHub's own
runners, so you don't need to keep a Mac awake for the paper-testing period. They never place orders —
same guard, same code path as the local `session`/`worker`.

1. **Add repo secrets** (Settings → Secrets and variables → Actions): `FYERS_APP_ID`, `FYERS_SECRET_KEY`,
   `FYERS_PIN`, `FYERS_REFRESH_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Get the refresh token by
   running `tradalgo login` once yourself locally (`.venv/bin/tradalgo login`, then read it back with
   `python -c "import keyring; print(keyring.get_password('tradalgo','FYERS_REFRESH_TOKEN'))"`) — the
   redirect URL stays the local one already in `config.yaml` (e.g. `https://127.0.0.1:5000/`); the login
   itself is always a manual, human-in-the-browser step, done once every ~15 days, never on a GitHub
   runner. Re-run it and update the secret when the refresh token expires (`tradalgo report`/Telegram
   will remind you).
2. **Push this branch.** `morning-screen.yml` runs at 07:00 IST on trading weekdays; `intraday-monitor.yml`
   runs roughly every 5 minutes from 09:15–15:31 IST. Both accept `workflow_dispatch` so you can trigger
   them by hand from the Actions tab to test.
3. **State persists across runs** on an orphan `runtime-state` branch (created automatically on first run)
   holding `data/tradalgo.db` and the session JSON — each 5-minute run is a fresh container, so this is how
   `tradalgo ci-cycle` (a single 5-minute cycle, then exit — see `tradalgo/cli.py`) picks up where the
   previous run left off. The candle cache and logs are *not* persisted there (too large / regenerable);
   each screen run rebuilds what it needs from FYERS/yfinance, and logs go to the workflow's uploaded
   artifacts instead.
4. **GitHub's cron has no delivery guarantee** — a run can fire a few minutes late, especially at busy
   times, and a missed run's bars are only replayed on the *next* run's frame (this is exactly the
   sleeping-Mac scenario the local design already has to tolerate). Do not treat a 5-minute cadence on
   GitHub Actions as more reliable than it is; the plan's Verification-step shadow run applies here too.
5. **This is for the plan's paper-testing and 5–6 month backtest-validation period only.** The app never
   places orders regardless of where it runs, so there is no "live" flag to flip — the way you eventually
   trust an alert enough to act on it manually is the M6 gate (`tradalgo backtest ...`) plus a clean shadow
   run, not a switch from paper to Actions or Actions to local.

## Trading costs

Backtest and paper-trade net R subtract modeled FYERS equity-intraday charges from `config.yaml` `costs:`. These replace the old flat ₹50 per trade. The charges are:
- brokerage per executed order, capped per order;
- STT on the sell side;
- exchange transaction charges;
- SEBI fees;
- stamp duty on the buy side;
- GST on brokerage, exchange charges and SEBI fees.

Verify the rates against https://fyers.in/charges before you trust backtest results.

## Parameter sweep

`tradalgo sweep --grid grid.example.yaml` runs a walk-forward sweep:
- ranks override combinations on the train period only;
- re-runs the top K on the out-of-sample test period;
- writes `data/reports/sweep-<ts>.md`, `.json` and, if a combination passes the gate, `sweep-<ts>-recommended.yaml`.

It never edits `config.yaml` and writes nothing to the database.

- **Default split:** train 2025-10-15 → 2026-04-30, test 2026-05-01 → 2026-09-11 (they must not overlap). The cache needs 20 prior 5m sessions before the train start, and `data_static/nse_holidays_<year>.yaml` for every year covered. A missing cached day stops the sweep with a `tradalgo backfill` hint instead of being skipped.
- **Memory:** each worker preloads all daily and 5m candles, about **250–350 MB peak RSS per worker** on the Nifty 100 cache (measured 242 MB after preload, 330 MB after a real run), so plan for roughly 1.5 GB with 4 workers. Default workers are `min(cpu_count - 1, 4)`. The progress line and the report show the measured peak.
- **Runtime:** about **6 s per combination per trading day per worker**, almost all in the engine (regime classification, detectors). The default split covers about 230 trading days: every combination on ~140 train days, the top K on ~92 test days. 60 combinations × 4 workers therefore take **several hours** (≈ 60 × 140 × 6 s ÷ 4 ≈ 3.5 h, plus the test phase). Start with `--max-combinations 60`, keep the Mac awake (`caffeinate -i`), and plug it in.
- **Resume:** every finished combination is appended to `data/reports/sweep-<ts>.partial.jsonl` as it completes. After an interruption, run the same command with `--resume data/reports/sweep-<ts>.partial.jsonl`. It refuses a checkpoint whose grid, seed or split differ, and skips the finished work.

## Before relying on live alerts

- Verify `data_static/nse_holidays_2026.yaml` (and the current year's file) against the official NSE
  holiday circular.
- **Do not trust live alerts until the M6 backtest gate is cleared**: expectancy must be > 0R after ₹50
  fixed cost and slippage, over at least 100 trades (`tradalgo backtest ...`). Otherwise tune thresholds
  or disable losing strategies in `config.yaml` and re-run.
- Run `tradalgo session` in shadow mode for a few days and check that every entry alert has a trigger,
  stop, 2R/3R target, qty, margin, invalidation price and valid-until time before treating it as
  actionable.
