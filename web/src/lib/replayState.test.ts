import { describe, it, expect } from "vitest";
import { replayStateAtPlayhead } from "./replayState";
import type { ReplayResponse } from "../api/types";

function buildReplay(): ReplayResponse {
  const candles = Array.from({ length: 12 }, (_, i) => ({
    time: 1000 + i * 300,
    open: 100 + i,
    high: 101 + i,
    low: 99 + i,
    close: 100 + i,
    volume: 100,
  }));
  return {
    trade: {
      id: "t1",
      trade_date: "2026-01-01",
      symbol: "TEST",
      strategy: "orb",
      net_r: 1,
      entry_price: 102,
    },
    candles,
    session_vwap: candles.map((c) => ({ time: c.time, value: c.close })),
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

describe("replayStateAtPlayhead", () => {
  it("before entry: flat, no open qty, next event is entry, stop is initial", () => {
    const replay = buildReplay();
    const state = replayStateAtPlayhead(replay, 1);
    expect(state.openQty).toBe(0);
    expect(state.unrealisedR).toBe(0);
    expect(state.nextEvent?.kind).toBe("entry");
    expect(state.currentStop).toBe(98);
  });

  it("after partial: half the qty remains, unrealised R reflects price vs entry/stop", () => {
    const replay = buildReplay();
    const state = replayStateAtPlayhead(replay, 5);
    expect(state.openQty).toBe(20);
    expect(state.nextEvent?.kind).toBe("trail_update");
    // price at index 5 close = 105, entry 102, stop 98, risk=4 -> (105-102)/4 = 0.75
    expect(state.unrealisedR).toBeCloseTo(0.75, 2);
  });

  it("after a trail: stop moves to the trailed value from stop_path", () => {
    const replay = buildReplay();
    const state = replayStateAtPlayhead(replay, 7);
    expect(state.openQty).toBe(20);
    expect(state.currentStop).toBe(102);
    expect(state.nextEvent?.kind).toBe("stop_hit");
  });

  it("after stop: qty flat again, no next event remaining", () => {
    const replay = buildReplay();
    const state = replayStateAtPlayhead(replay, 10);
    expect(state.openQty).toBe(0);
    expect(state.nextEvent).toBeNull();
  });
});
