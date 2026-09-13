import type { ReplayMarker, ReplayResponse } from "../api/types";

export interface ReplayStateAtPlayhead {
  time: number;
  price: number | null;
  openQty: number;
  unrealisedR: number;
  currentStop: number;
  nextEvent: ReplayMarker | null;
}

/**
 * Derive the side-panel state at a given bar index (playhead) from the
 * replay payload's markers, stop_path and levels. Pure function — no
 * chart/DOM deps — so it's unit-testable and reusable by both the chart
 * and the side panel.
 *
 * `currentStop` prefers the server-provided `stop_path` (the effective
 * stop over time: initial stop at entry, then one point per trail_update)
 * when present; it falls back to replaying `trail_update.new_stop` (or
 * `.price` for older trades that don't carry `new_stop`) from markers.
 */
export function replayStateAtPlayhead(
  replay: ReplayResponse,
  playheadIndex: number
): ReplayStateAtPlayhead {
  const candle = replay.candles[Math.min(playheadIndex, replay.candles.length - 1)];
  const time = candle?.time ?? 0;

  const occurred = replay.markers.filter((m) => m.time <= time);
  const upcoming = replay.markers.filter((m) => m.time > time);
  const nextEvent = upcoming.length > 0 ? upcoming[0] : null;

  let openQty = 0;
  let currentStop = replay.levels.stop;
  let entryPrice = replay.levels.entry;

  if (replay.stop_path && replay.stop_path.length > 0) {
    const activeStops = replay.stop_path.filter((p) => p.time <= time);
    if (activeStops.length > 0) currentStop = activeStops[activeStops.length - 1].value;
  }

  for (const m of occurred) {
    if (m.kind === "entry") {
      openQty += m.qty;
      entryPrice = m.price;
    } else if (
      m.kind === "partial_exit" ||
      m.kind === "runner_exit" ||
      m.kind === "hard_exit" ||
      m.kind === "stop_hit"
    ) {
      openQty -= m.qty;
    } else if (m.kind === "trail_update" && !replay.stop_path) {
      currentStop = m.new_stop ?? m.price;
    }
  }
  openQty = Math.max(0, openQty);

  const price = candle?.close ?? null;
  const risk = Math.abs(entryPrice - replay.levels.stop);
  const unrealisedR =
    openQty > 0 && price !== null && risk > 0 ? (price - entryPrice) / risk : 0;

  return {
    time,
    price,
    openQty,
    unrealisedR: Number(unrealisedR.toFixed(2)),
    currentStop,
    nextEvent,
  };
}
