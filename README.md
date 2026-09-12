# tradalgo

NSE intraday screener and alert system for Nifty 50 + Nifty Next 50. **Alerts only — it never places orders.**
Strategy spec: `llm_intraday_stock_trading_spec.md`. Plan: `docs/superpowers/plans/2026-09-13-tradalgo-master.md`.

## Setup

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/tradalgo init          # creates data/tradalgo.db (SQLite, WAL mode)
.venv/bin/pytest
```

Secrets are stored in macOS Keychain, never in files:

```bash
.venv/bin/python -c "import keyring; keyring.set_password('tradalgo', 'TELEGRAM_BOT_TOKEN', '<token>')"
```

Tunable parameters (capital, risk, shortlist size, entry windows) live in `config.yaml` and are validated on load.

## Before relying on live alerts

- Verify `data_static/nse_holidays_2026.yaml` against the official NSE holiday circular.
- launchd does not wake a sleeping Mac. Schedule a wake before the 07:00 screener:
  `sudo pmset repeat wakeorpoweron MTWRF 06:55:00`
