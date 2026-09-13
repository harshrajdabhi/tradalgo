import * as F from "./fixtures";

// Isolated mock transport used only when VITE_MOCK=1. Never imported by
// production code paths outside src/api/client.ts's MOCK branch.
let liveTick = 0;

export async function mockFetch(path: string, init?: RequestInit): Promise<unknown> {
  const [route, query] = path.split("?");
  const method = init?.method ?? "GET";
  const parts = route.split("/").filter(Boolean);

  await new Promise((r) => setTimeout(r, 40));

  if (route === "/health") return F.health;
  if (route === "/now") return F.now;
  if (route === "/shortlist") return F.shortlist;
  if (route === "/signals") return F.signals;
  if (route === "/positions") return F.positions;
  if (route === "/alerts") return F.alerts;
  if (parts[0] === "alerts" && parts[2] === "resend" && method === "POST") {
    return { ok: true };
  }
  if (route === "/journal") return F.journal;
  if (route === "/analytics") return F.analytics;
  if (route === "/jobs") return F.jobs;
  if (route === "/backtests" && method === "GET") return F.backtestRuns;
  if (route === "/backtests" && method === "POST") {
    const body = JSON.parse(String(init?.body ?? "{}"));
    if (body.to && body.from && body.to < body.from) {
      throw Object.assign(new Error("end date is before start date"), { status: 422 });
    }
    return { id: 999 };
  }
  if (parts[0] === "backtests" && parts[2] === "cancel") return { ok: true };
  if (parts[0] === "backtests" && parts[2] === "live") {
    liveTick += 1;
    const grown = Math.min(F.backtestLive.equity_curve.length, 37 + liveTick);
    const progress = Math.min(100, F.backtestLive.progress_pct + liveTick * 3);
    return {
      ...F.backtestLive,
      progress_pct: progress,
      status: progress >= 100 ? "finished" : "running",
      equity_curve: F.backtestLive.equity_curve.slice(0, grown),
      trades_so_far: grown,
    };
  }
  if (parts[0] === "backtests" && parts[2] === "trades" && parts.length === 3) {
    return F.backtestTrades;
  }
  if (parts[0] === "backtests" && parts[2] === "trades" && parts[4] === "replay") {
    return { ...F.replay, trade: F.backtestTrades.find((t) => String(t.id) === parts[3]) ?? F.replay.trade };
  }
  if (parts[0] === "backtests" && parts.length === 2) return F.backtestDetailFinished;
  if (parts[0] === "candles") return { candles: F.replay.candles, session_vwap: F.replay.session_vwap };
  if (route === "/kill-switch") return { on: JSON.parse(String(init?.body ?? "{}")).on };
  if (route === "/sweeps") return F.sweeps;
  if (parts[0] === "sweeps" && parts.length === 2) return F.sweepDetail;
  if (route === "/settings" && method === "GET") return F.settings;
  if (route === "/settings" && method === "PUT") {
    const body = JSON.parse(String(init?.body ?? "{}"));
    if (typeof body.max_risk_pct === "number" && body.max_risk_pct > 0.03) {
      throw Object.assign(new Error("max_risk_pct must be at most 0.03"), { status: 422 });
    }
    return { ok: true, backup: "/data/settings.backup.yaml" };
  }

  void query;
  throw new Error(`mockFetch: no fixture for ${method} ${path}`);
}
