import { describe, it, expect } from "vitest";
import { visibleReplay, sessionSlots } from "./visibleReplay";
import type { ReplayResponse } from "../api/types";

// 09:15 IST on 2026-08-14 = 03:45 UTC
const START = Date.UTC(2026, 7, 14, 3, 45) / 1000;

function buildReplay(): ReplayResponse {
  const candles = Array.from({ length: 12 }, (_, i) => ({
    time: START + i * 300,
    open: 100 + i,
    high: 101 + i,
    low: 99 + i,
    close: 100 + i,
    volume: 100,
  }));
  return {
    trade: { id: "t1", trade_date: "2026-08-14", symbol: "T", strategy: "orb", entry_price: 102, net_r: 1 },
    candles,
    session_vwap: candles.map((c) => ({ time: c.time, value: c.close - 1 })),
    levels: { entry: 102, stop: 98, target_partial: 106, target_runner: 112 },
    markers: [
      { time: candles[2].time, kind: "entry", price: 102, qty: 40, r: 0 },
      { time: candles[5].time, kind: "partial_exit", price: 106, qty: 20, r: 1 },
      { time: candles[6].time, kind: "trail_update", price: 102, qty: 20, r: 0, new_stop: 102 },
      { time: candles[9].time, kind: "stop_hit", price: 102, qty: 20, r: 0 },
    ],
    stop_path: [
      { time: candles[2].time, value: 98 },
      { time: candles[6].time, value: 102 },
    ],
  };
}

describe("visibleReplay", () => {
  it("before entry: no vwap beyond t, no levels, no stop path, no markers", () => {
    const r = buildReplay();
    const t = r.candles[1].time;
    const v = visibleReplay(r, t);
    expect(v.candles).toHaveLength(2);
    expect(v.vwap).toHaveLength(2);
    expect(v.vwap.every((p) => p.time <= t)).toBe(true);
    expect(v.levels).toBeNull();
    expect(v.stopPath).toHaveLength(0);
    expect(v.markers).toHaveLength(0);
  });

  it("at the entry bar: planned levels appear, stop path starts at the initial stop", () => {
    const r = buildReplay();
    const v = visibleReplay(r, r.candles[2].time);
    expect(v.levels?.entry).toBe(102);
    expect(v.stopPath).toEqual([{ time: r.candles[2].time, value: 98 }]);
    expect(v.markers.map((m) => m.kind)).toEqual(["entry"]);
  });

  it("after partial: partial marker visible, no trail yet, stop still initial", () => {
    const r = buildReplay();
    const v = visibleReplay(r, r.candles[5].time);
    expect(v.markers.map((m) => m.kind)).toEqual(["entry", "partial_exit"]);
    expect(v.stopPath[v.stopPath.length - 1].value).toBe(98);
  });

  it("after a trail_update: stop line shows new_stop only from that time", () => {
    const r = buildReplay();
    const before = visibleReplay(r, r.candles[5].time);
    expect(before.stopPath.some((p) => p.value === 102)).toBe(false);
    const after = visibleReplay(r, r.candles[7].time);
    expect(after.stopPath[after.stopPath.length - 1]).toEqual({ time: r.candles[6].time, value: 102 });
    expect(after.stopPath.every((p) => p.time <= r.candles[7].time)).toBe(true);
  });

  it("after final exit: all markers visible, nothing beyond t", () => {
    const r = buildReplay();
    const t = r.candles[10].time;
    const v = visibleReplay(r, t);
    expect(v.markers.map((m) => m.kind)).toContain("stop_hit");
    expect(v.candles.every((c) => c.time <= t)).toBe(true);
  });

  it("without stop_path, derives the stop line from entry + trail_update.new_stop", () => {
    const r = buildReplay();
    delete r.stop_path;
    const v = visibleReplay(r, r.candles[7].time);
    expect(v.stopPath.map((p) => p.value)).toEqual([98, 102]);
  });
});

describe("sessionSlots", () => {
  it("covers 09:15 to 15:25 IST in 5 minute steps (75 slots)", () => {
    const slots = sessionSlots(START + 600);
    expect(slots).toHaveLength(75);
    expect(slots[0]).toBe(START);
    expect(slots[74]).toBe(START + 74 * 300);
  });
});
