#!/usr/bin/env bash
# Run tradalgo locally: loads secrets from .env, then starts the worker (Telegram sender/poller,
# maintenance) and the dashboard in the background and the market-hours session in the foreground.
#
# Usage:
#   scripts/run_local.sh              # worker + dashboard + session (blocks until Ctrl+C)
#   scripts/run_local.sh screen       # just run the 07:00 screener once, then exit
#   scripts/run_local.sh preopen      # just run the 09:08 pre-open annotation once, then exit
#   scripts/run_local.sh session-only # session in the foreground, no worker/dashboard
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
else
  echo "No .env found — copy .env.example to .env and fill in your secrets first." >&2
  exit 1
fi

TRADALGO="${VIRTUAL_ENV:-.venv}/bin/tradalgo"
[ -x "$TRADALGO" ] || TRADALGO=".venv/bin/tradalgo"

"$TRADALGO" init

case "${1:-}" in
  screen)
    exec "$TRADALGO" screen
    ;;
  preopen)
    exec "$TRADALGO" preopen
    ;;
  session-only)
    exec "$TRADALGO" session
    ;;
  "")
    pids=()
    cleanup() {
      echo "stopping..."
      for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    }
    trap cleanup EXIT INT TERM

    "$TRADALGO" worker &
    pids+=($!)
    echo "worker started (pid $!)"

    "$TRADALGO" dashboard &
    pids+=($!)
    echo "dashboard started (pid $!) - http://127.0.0.1:8501"

    echo "starting the live session (Ctrl+C to stop everything)..."
    "$TRADALGO" session
    ;;
  *)
    echo "usage: $0 [screen|preopen|session-only]" >&2
    exit 1
    ;;
esac
