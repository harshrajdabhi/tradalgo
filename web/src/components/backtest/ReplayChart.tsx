import { useEffect, useRef } from "react";
import { createChart, ColorType, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { useTheme } from "@mui/material/styles";
import type { ReplayResponse } from "../../api/types";

// lightweight-charts always renders time labels in UTC regardless of the
// viewer's local timezone. Our timestamps are real IST wall-clock moments
// stored as UTC epoch seconds, so without this shift the axis reads five
// and a half hours early (e.g. "04:00" instead of "09:30"). Shifting every
// timestamp fed to the chart by the IST offset makes the UTC-labelled axis
// display the correct IST time — a display-only transform; state/logic
// (replayStateAtPlayhead, formatIstTime) use the real timestamps untouched.
const IST_OFFSET_SEC = 19800; // +5:30
const toChartTime = (t: number) => (t + IST_OFFSET_SEC) as never;

const MARKER_SHAPE: Record<string, "circle" | "arrowUp" | "arrowDown" | "square"> = {
  entry: "arrowUp",
  partial_exit: "circle",
  trail_update: "square",
  runner_exit: "arrowDown",
  stop_hit: "arrowDown",
  hard_exit: "arrowDown",
};

export default function ReplayChart({
  replay,
  playheadIndex,
}: {
  replay: ReplayResponse;
  playheadIndex: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const theme = useTheme();

  useEffect(() => {
    if (!ref.current) return;
    const t = theme.palette;
    const chart = createChart(ref.current, {
      width: ref.current.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: t.text.secondary,
        fontFamily: theme.typography.fontFamily,
      },
      grid: { vertLines: { color: t.divider }, horzLines: { color: t.divider } },
      rightPriceScale: { borderColor: t.divider },
      timeScale: { borderColor: t.divider, timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: t.success.main,
      downColor: t.error.main,
      borderVisible: false,
      wickUpColor: t.success.main,
      wickDownColor: t.error.main,
    });
    seriesRef.current = candleSeries;

    const vwapSeries = chart.addLineSeries({ color: "#5B7C99", lineWidth: 1, title: "VWAP" });
    vwapSeries.setData(
      replay.session_vwap.map((p) => ({ time: toChartTime(p.time), value: p.value }))
    );

    if (replay.stop_path && replay.stop_path.length > 0) {
      const stopPathSeries = chart.addLineSeries({
        color: t.error.main,
        lineWidth: 1,
        lineStyle: 3,
        lineType: 1, // stepped
        title: "trailed stop",
      });
      stopPathSeries.setData(
        replay.stop_path.map((p) => ({ time: toChartTime(p.time), value: p.value }))
      );
    }

    candleSeries.createPriceLine({
      price: replay.levels.entry,
      color: t.text.primary,
      lineWidth: 1,
      lineStyle: 2,
      title: "entry",
    });
    candleSeries.createPriceLine({
      price: replay.levels.stop,
      color: t.error.main,
      lineWidth: 2,
      lineStyle: 0,
      title: "stop",
    });
    candleSeries.createPriceLine({
      price: replay.levels.target_partial,
      color: t.success.main,
      lineWidth: 1,
      lineStyle: 0,
      title: "partial",
    });
    candleSeries.createPriceLine({
      price: replay.levels.target_runner,
      color: t.success.main,
      lineWidth: 1,
      lineStyle: 1,
      title: "runner",
    });

    const onResize = () => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replay, theme]);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;
    const visible = replay.candles.slice(0, playheadIndex + 1);
    series.setData(
      visible.map((c) => ({
        time: toChartTime(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );
    const visibleTimes = new Set(visible.map((c) => c.time));
    const markers = replay.markers
      .filter((m) => visibleTimes.has(m.time))
      .map((m) => ({
        time: toChartTime(m.time),
        position: (m.kind === "entry" ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar",
        color: m.kind === "entry" ? theme.palette.text.primary : theme.palette.warning.main,
        shape: MARKER_SHAPE[m.kind] ?? "circle",
        text: m.kind,
      }));
    series.setMarkers(markers);
    chart.timeScale().fitContent();
  }, [replay, playheadIndex, theme]);

  return <div ref={ref} style={{ width: "100%" }} />;
}
