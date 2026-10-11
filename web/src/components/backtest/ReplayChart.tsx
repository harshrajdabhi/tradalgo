import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
} from "lightweight-charts";
import { useTheme } from "@mui/material/styles";
import type { ReplayResponse } from "../../api/types";
import { sessionSlots, visibleReplay } from "../../lib/visibleReplay";

// lightweight-charts labels time in UTC regardless of viewer timezone; our
// timestamps are IST moments as UTC epoch seconds, so shift for display only.
const IST_OFFSET_SEC = 19800;
const toChartTime = (t: number) => (t + IST_OFFSET_SEC) as never;

// Neutral (ink) markers; sign colour lives on the R labels in the side panel.
const MARKER_SHAPE: Record<string, "circle" | "arrowUp" | "arrowDown" | "square"> = {
  entry: "arrowUp",
  partial_exit: "circle",
  trail_update: "square",
  runner_exit: "arrowDown",
  stop_hit: "arrowDown",
  hard_exit: "arrowDown",
};

const withAlpha = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
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
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const vwapRef = useRef<ISeriesApi<"Line"> | null>(null);
  const stopRef = useRef<ISeriesApi<"Line"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const rangeSet = useRef(false);
  const theme = useTheme();

  // Chart creation: full-session time axis, set once, never re-fitted.
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
      timeScale: {
        borderColor: t.divider,
        timeVisible: true,
        secondsVisible: false,
        lockVisibleTimeRangeOnResize: true,
      },
    });
    chartRef.current = chart;

    const candles = chart.addCandlestickSeries({
      upColor: t.success.main,
      downColor: t.error.main,
      borderVisible: false,
      wickUpColor: t.success.main,
      wickDownColor: t.error.main,
    });
    candleRef.current = candles;
    vwapRef.current = chart.addLineSeries({
      color: "#5B7C99",
      lineWidth: 1,
      title: "VWAP",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    stopRef.current = chart.addLineSeries({
      color: withAlpha(theme.palette.mode === "light" ? "#8C3B34" : "#D98E82", 0.55),
      lineWidth: 2,
      lineType: 1, // stepped
      title: "trailing stop",
      lastValueVisible: false,
      priceLineVisible: false,
    });

    const slots = sessionSlots(replay.candles[0]?.time ?? 0);
    candles.setData(slots.map((s) => ({ time: toChartTime(s) })));
    rangeSet.current = false;

    const onResize = () => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      linesRef.current = [];
    };
  }, [replay, theme]);

  // Playhead: clip everything to time <= t.
  useEffect(() => {
    const candles = candleRef.current;
    if (!candles || !vwapRef.current || !stopRef.current) return;
    const t = theme.palette;
    const tNow = replay.candles[Math.min(playheadIndex, replay.candles.length - 1)]?.time ?? 0;
    const v = visibleReplay(replay, tNow);

    const have = new Map(v.candles.map((c) => [c.time, c]));
    candles.setData(
      sessionSlots(replay.candles[0]?.time ?? 0).map((s) => {
        const c = have.get(s);
        return c
          ? { time: toChartTime(s), open: c.open, high: c.high, low: c.low, close: c.close }
          : { time: toChartTime(s) };
      })
    );
    if (!rangeSet.current && chartRef.current) {
      // Full session on the axis, set once per replay (no fitContent).
      chartRef.current.timeScale().setVisibleLogicalRange({ from: -1, to: 76 });
      rangeSet.current = true;
    }
    vwapRef.current.setData(v.vwap.map((p) => ({ time: toChartTime(p.time), value: p.value })));
    stopRef.current.setData(v.stopPath.map((p) => ({ time: toChartTime(p.time), value: p.value })));

    candles.setMarkers(
      v.markers.map((m) => ({
        time: toChartTime(m.time),
        position: (m.kind === "entry" ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar",
        color: t.text.primary,
        shape: MARKER_SHAPE[m.kind] ?? "circle",
        text: m.kind.replace("_", " "),
      }))
    );

    linesRef.current.forEach((l) => candles.removePriceLine(l));
    linesRef.current = [];
    if (v.levels) {
      const mk = (price: number, color: string, lineStyle: number, title: string) =>
        linesRef.current.push(
          candles.createPriceLine({ price, color, lineWidth: 1, lineStyle, title })
        );
      mk(v.levels.entry, t.text.primary, 2, "entry");
      mk(v.levels.stop, t.error.main, 0, "stop");
      mk(v.levels.target_partial, t.success.main, 0, "partial");
      mk(v.levels.target_runner, t.success.main, 1, "runner");
    }
  }, [replay, playheadIndex, theme]);

  return <div ref={ref} style={{ width: "100%" }} />;
}
