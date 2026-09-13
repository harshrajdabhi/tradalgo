import * as T from "./types";
import { mockFetch } from "../mocks/mockFetch";

const MOCK = import.meta.env.VITE_MOCK === "1";

export class ApiError extends Error {
  detail: string;
  status: number;
  constructor(detail: string, status: number) {
    super(detail);
    this.detail = detail;
    this.status = status;
  }
}

async function request<Res>(path: string, init?: RequestInit): Promise<Res> {
  if (MOCK) {
    try {
      return (await mockFetch(path, init)) as Res;
    } catch (e) {
      const err = e as { message?: string; status?: number };
      throw new ApiError(err.message ?? "mock error", err.status ?? 500);
    }
  }
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as T.ApiErrorBody;
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as Res;
  return (await res.json()) as Res;
}

export const api = {
  health: () => request<T.HealthResponse>("/health"),
  now: (date?: string) => request<T.NowResponse>(`/now${qs({ date })}`),
  shortlist: (date?: string) => request<T.ShortlistRow[]>(`/shortlist${qs({ date })}`),
  signals: (date?: string) => request<T.SignalRow[]>(`/signals${qs({ date })}`),
  positions: () => request<T.Position[]>("/positions"),
  alerts: (status?: string, date?: string) =>
    request<T.AlertsResponse>(`/alerts${qs({ status, date })}`),
  resendAlert: (id: number) =>
    request<{ ok: boolean }>(`/alerts/${id}/resend`, { method: "POST" }),
  journal: (params: { from?: string; to?: string; strategy?: string; symbol?: string }) =>
    request<T.JournalRow[]>(`/journal${qs(params)}`),
  analytics: () => request<T.AnalyticsResponse>("/analytics"),
  jobs: () => request<T.JobsResponse>("/jobs"),
  backtests: () => request<T.BacktestRun[]>("/backtests"),
  queueBacktest: (params: T.BacktestParams) =>
    request<{ id: number }>("/backtests", { method: "POST", body: JSON.stringify(params) }),
  cancelBacktest: (id: number) =>
    request<{ ok: boolean }>(`/backtests/${id}/cancel`, { method: "POST" }),
  backtestDetail: (id: number) => request<T.BacktestDetailResponse>(`/backtests/${id}`),
  backtestLive: (id: number) => request<T.BacktestLiveResponse>(`/backtests/${id}/live`),
  backtestTrades: (id: number, params?: { strategy?: string; symbol?: string; outcome?: string }) =>
    request<T.Trade[]>(`/backtests/${id}/trades${qs(params ?? {})}`),
  backtestReplay: (id: number, tradeId: string) =>
    request<T.ReplayResponse>(`/backtests/${id}/trades/${tradeId}/replay`),
  candles: (symbol: string, date?: string) =>
    request<T.CandlesResponse>(`/candles/${symbol}${qs({ date })}`),
  killSwitch: (on: boolean) =>
    request<{ on: boolean }>(`/kill-switch`, { method: "POST", body: JSON.stringify({ on }) }),
  sweeps: () => request<T.SweepSummary[]>("/sweeps"),
  sweepDetail: (name: string) => request<T.SweepDetailResponse>(`/sweeps/${name}`),
  getSettings: () => request<T.Settings>("/settings"),
  putSettings: (settings: T.Settings) =>
    request<{ ok: boolean; backup: string | null }>("/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
};

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
}
