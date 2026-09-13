import { useEffect, useRef } from "react";
import { createChart, ColorType, type IChartApi } from "lightweight-charts";
import { useTheme } from "@mui/material/styles";
import type { Candle, VwapPoint } from "../api/types";

// See ReplayChart.tsx for why this shift exists: lightweight-charts labels
// time axes in UTC regardless of viewer timezone; our timestamps are real
// IST moments, so this display-only shift keeps the axis reading correctly.
const IST_OFFSET_SEC = 19800;
const toChartTime = (t: number) => (t + IST_OFFSET_SEC) as never;

interface Props {
  candles: Candle[];
  vwap?: VwapPoint[];
  levels?: { entry?: number; stop?: number };
  height?: number;
}

export default function MiniCandleChart({ candles, vwap, levels, height = 140 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();

  useEffect(() => {
    if (!ref.current) return;
    const t = theme.palette;
    const chart: IChartApi = createChart(ref.current, {
      width: ref.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: t.text.secondary,
        fontFamily: theme.typography.fontFamily,
        fontSize: 11,
      },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      rightPriceScale: { borderColor: t.divider },
      timeScale: { borderColor: t.divider, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });

    const series = chart.addCandlestickSeries({
      upColor: t.success.main,
      downColor: t.error.main,
      borderVisible: false,
      wickUpColor: t.success.main,
      wickDownColor: t.error.main,
    });
    series.setData(
      candles.map((c) => ({
        time: toChartTime(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );

    if (vwap && vwap.length > 0) {
      const vwapSeries = chart.addLineSeries({ color: "#5B7C99", lineWidth: 1 });
      vwapSeries.setData(vwap.map((p) => ({ time: toChartTime(p.time), value: p.value })));
    }

    if (levels?.entry !== undefined) {
      series.createPriceLine({
        price: levels.entry,
        color: t.text.primary,
        lineWidth: 1,
        lineStyle: 2,
        title: "entry",
      });
    }
    if (levels?.stop !== undefined) {
      series.createPriceLine({
        price: levels.stop,
        color: t.error.main,
        lineWidth: 1,
        lineStyle: 0,
        title: "stop",
      });
    }

    chart.timeScale().fitContent();

    const onResize = () => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [candles, vwap, levels, height, theme]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
