import type { Candle, ReplayMarker, ReplayResponse, StopPathPoint, VwapPoint } from "../api/types";

const IST_OFFSET = 19800;
const SESSION_START = 9 * 3600 + 15 * 60; // 09:15 IST, seconds from IST midnight
const SESSION_END = 15 * 3600 + 30 * 60; // 15:30 IST (exclusive; last 5m bar opens 15:25)
const SLOT = 300;

export interface VisibleReplay {
  candles: Candle[];
  vwap: VwapPoint[];
  stopPath: StopPathPoint[];
  markers: ReplayMarker[];
  /** Planned levels; null until the entry bar. */
  levels: ReplayResponse["levels"] | null;
}

/** Every 5m slot start (UTC epoch s) of the IST session containing `anyTime`. */
export function sessionSlots(anyTime: number): number[] {
  const istDayStart = Math.floor((anyTime + IST_OFFSET) / 86400) * 86400 - IST_OFFSET;
  const slots: number[] = [];
  for (let s = SESSION_START; s < SESSION_END; s += SLOT) slots.push(istDayStart + s);
  return slots;
}

/**
 * What the replay may show at playhead time `t`: everything is clipped to
 * time <= t so no future information leaks. Planned levels show from the
 * entry bar onward; the stop line is the effective stop up to t only.
 */
export function visibleReplay(replay: ReplayResponse, t: number): VisibleReplay {
  const candles = replay.candles.filter((c) => c.time <= t);
  const vwap = replay.session_vwap.filter((p) => p.time <= t);
  const markers = replay.markers.filter((m) => m.time <= t);
  const entry = replay.markers.find((m) => m.kind === "entry");
  const entered = !!entry && entry.time <= t;

  let fullPath: StopPathPoint[] = replay.stop_path ?? [];
  if (!replay.stop_path && entry) {
    fullPath = [{ time: entry.time, value: replay.levels.stop }];
    for (const m of replay.markers) {
      if (m.kind === "trail_update") fullPath.push({ time: m.time, value: m.new_stop ?? m.price });
    }
  }
  const stopPath = entered ? fullPath.filter((p) => p.time <= t) : [];

  return { candles, vwap, stopPath, markers, levels: entered ? replay.levels : null };
}
