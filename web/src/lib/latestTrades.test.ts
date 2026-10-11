import { describe, it, expect } from "vitest";
import { latestTradeRows } from "./latestTrades";

describe("latestTradeRows", () => {
  it("returns newest first, capped at 20", () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({
      exit_ts: `2026-09-14T09:${String(i).padStart(2, "0")}:00Z`,
      symbol: `S${i}`,
      strategy: "orb",
      net_r: i % 2 ? -1 : 1,
    }));
    const out = latestTradeRows(rows);
    expect(out).toHaveLength(20);
    expect(out[0].symbol).toBe("S24");
  });

  it("tolerates missing fields", () => {
    const out = latestTradeRows([{ symbol: "X" }]);
    expect(out[0]).toMatchObject({ symbol: "X", strategy: "", netR: null });
  });
});
