import { formatIstTime } from "./format";

export interface LatestTradeRow {
  time: string;
  sortKey: string;
  symbol: string;
  strategy: string;
  netR: number | null;
}

/** Newest first, max 20, tolerant of the loosely-typed API rows. */
export function latestTradeRows(rows: Array<Record<string, unknown>>): LatestTradeRow[] {
  return rows
    .map((r) => {
      const raw = String(r.exit_ts ?? r.time ?? "");
      return {
        time: raw.includes("T") ? formatIstTime(raw) : raw,
        sortKey: raw,
        symbol: String(r.symbol ?? ""),
        strategy: String(r.strategy ?? ""),
        netR: typeof r.net_r === "number" ? r.net_r : null,
      };
    })
    .sort((a, b) => (a.sortKey < b.sortKey ? 1 : a.sortKey > b.sortKey ? -1 : 0))
    .slice(0, 20);
}
