import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { BacktestParams, Settings } from "./types";

const SLOW = 15000;
const FAST = 3000;

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: SLOW });

export const useNow = (date?: string) =>
  useQuery({ queryKey: ["now", date], queryFn: () => api.now(date), refetchInterval: SLOW });

export const useShortlist = (date?: string) =>
  useQuery({ queryKey: ["shortlist", date], queryFn: () => api.shortlist(date), refetchInterval: SLOW });

export const useSignals = (date?: string) =>
  useQuery({ queryKey: ["signals", date], queryFn: () => api.signals(date), refetchInterval: SLOW });

export const usePositions = () =>
  useQuery({ queryKey: ["positions"], queryFn: api.positions, refetchInterval: SLOW });

export const useAlerts = (status?: string, date?: string) =>
  useQuery({ queryKey: ["alerts", status, date], queryFn: () => api.alerts(status, date), refetchInterval: SLOW });

export const useResendAlert = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.resendAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
};

export const useJournal = (params: { from?: string; to?: string; strategy?: string; symbol?: string }) =>
  useQuery({ queryKey: ["journal", params], queryFn: () => api.journal(params) });

export const useAnalytics = () =>
  useQuery({ queryKey: ["analytics"], queryFn: api.analytics, refetchInterval: SLOW });

export const useJobs = () =>
  useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: SLOW });

export const useBacktests = () =>
  useQuery({ queryKey: ["backtests"], queryFn: api.backtests, refetchInterval: SLOW });

export const useQueueBacktest = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: BacktestParams) => api.queueBacktest(params),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backtests"] }),
  });
};

export const useCancelBacktest = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.cancelBacktest(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backtests"] }),
  });
};

export const useBacktestDetail = (id: number) =>
  useQuery({ queryKey: ["backtest", id], queryFn: () => api.backtestDetail(id) });

export const useBacktestLive = (id: number, status?: string) =>
  useQuery({
    queryKey: ["backtestLive", id],
    queryFn: () => api.backtestLive(id),
    refetchInterval: (query) => {
      const s = query.state.data?.status ?? status;
      return s === "running" || s === "queued" ? FAST : false;
    },
  });

export const useBacktestTrades = (id: number, filters?: { strategy?: string; symbol?: string; outcome?: string }) =>
  useQuery({ queryKey: ["backtestTrades", id, filters], queryFn: () => api.backtestTrades(id, filters) });

export const useReplay = (id: number, tradeId: string | null) =>
  useQuery({
    queryKey: ["replay", id, tradeId],
    queryFn: () => api.backtestReplay(id, tradeId as string),
    enabled: !!tradeId,
  });

export const useKillSwitch = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) => api.killSwitch(on),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["health"] }),
  });
};

export const useSweeps = () =>
  useQuery({ queryKey: ["sweeps"], queryFn: api.sweeps, refetchInterval: SLOW });

export const useSweepDetail = (name: string) =>
  useQuery({ queryKey: ["sweep", name], queryFn: () => api.sweepDetail(name) });

export const useSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: api.getSettings });

export const usePutSettings = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Settings) => api.putSettings(settings),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
};
