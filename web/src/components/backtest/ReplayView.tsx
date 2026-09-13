import { useEffect, useMemo, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import Slider from "@mui/material/Slider";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PauseIcon from "@mui/icons-material/Pause";
import SkipPreviousIcon from "@mui/icons-material/SkipPrevious";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import { useBacktestTrades, useReplay } from "../../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../StateBox";
import ReplayChart from "./ReplayChart";
import { replayStateAtPlayhead } from "../../lib/replayState";
import { formatR, formatIstTime } from "../../lib/format";

export default function ReplayView({
  backtestId,
  initialTradeId,
  onExit,
}: {
  backtestId: number;
  initialTradeId: string | null;
  onExit: () => void;
}) {
  const tradesQ = useBacktestTrades(backtestId);
  const [tradeId, setTradeId] = useState<string | null>(initialTradeId);
  const [playheadIndex, setPlayheadIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!tradeId && tradesQ.data && tradesQ.data.length > 0) {
      setTradeId(String(tradesQ.data[0].id));
    }
  }, [tradeId, tradesQ.data]);

  const replayQ = useReplay(backtestId, tradeId);

  useEffect(() => {
    setPlayheadIndex(0);
    setPlaying(false);
  }, [tradeId]);

  const maxIndex = (replayQ.data?.candles.length ?? 1) - 1;

  useEffect(() => {
    if (playing && intervalRef.current === null) {
      intervalRef.current = setInterval(() => {
        setPlayheadIndex((i) => {
          if (i >= maxIndex) {
            setPlaying(false);
            return i;
          }
          return i + 1;
        });
      }, 600 / speed);
    }
    if (!playing && intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [playing, speed, maxIndex]);

  const trades = tradesQ.data ?? [];
  const currentIdx = trades.findIndex((t) => String(t.id) === tradeId);

  function gotoTrade(delta: number) {
    if (currentIdx < 0) return;
    const next = trades[currentIdx + delta];
    if (next) setTradeId(String(next.id));
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === " ") {
        e.preventDefault();
        setPlaying((p) => !p);
      } else if (e.key === "ArrowRight") {
        setPlayheadIndex((i) => Math.min(maxIndex, i + 1));
      } else if (e.key === "ArrowLeft") {
        setPlayheadIndex((i) => Math.max(0, i - 1));
      } else if (e.key === "ArrowUp") {
        setSpeed((s) => Math.min(5, s === 1 ? 2 : 5));
      } else if (e.key === "ArrowDown") {
        setSpeed((s) => (s === 5 ? 2 : 1));
      } else if (e.key === "]") {
        gotoTrade(1);
      } else if (e.key === "[") {
        gotoTrade(-1);
      } else if (e.key === "Escape") {
        onExit();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxIndex, currentIdx, trades]);

  const state = useMemo(
    () => (replayQ.data ? replayStateAtPlayhead(replayQ.data, playheadIndex) : null),
    [replayQ.data, playheadIndex]
  );

  if (tradesQ.isLoading) return <LoadingBox label="Loading trades" />;
  if (tradesQ.isError) return <ErrorBox text="Couldn't load trades." />;
  if (trades.length === 0) return <EmptyBox text="No trades to replay in this run." />;
  if (!tradeId) return <LoadingBox label="Selecting trade" />;
  if (replayQ.isLoading) return <LoadingBox label="Loading replay" />;
  if (replayQ.isError || !replayQ.data)
    return <ErrorBox text="No price data for this session. The trade may be outside the stored candle range." />;

  const replay = replayQ.data;

  return (
    <Box>
      <Grid container spacing={2}>
        <Grid item xs={12} md={9}>
          <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
            <Typography variant="h6">
              {replay.trade.symbol} · {replay.trade.trade_date}
            </Typography>
            <Box>
              <IconButton size="small" onClick={() => gotoTrade(-1)} disabled={currentIdx <= 0} aria-label="Previous trade">
                <SkipPreviousIcon />
              </IconButton>
              <IconButton
                size="small"
                onClick={() => gotoTrade(1)}
                disabled={currentIdx < 0 || currentIdx >= trades.length - 1}
                aria-label="Next trade"
              >
                <SkipNextIcon />
              </IconButton>
            </Box>
          </Box>

          <ReplayChart replay={replay} playheadIndex={playheadIndex} />

          <Box sx={{ display: "flex", alignItems: "center", gap: 2, mt: 1 }}>
            <IconButton onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pause" : "Play"}>
              {playing ? <PauseIcon /> : <PlayArrowIcon />}
            </IconButton>
            <Slider
              size="small"
              min={0}
              max={maxIndex}
              value={playheadIndex}
              onChange={(_, v) => setPlayheadIndex(v as number)}
              sx={{ flexGrow: 1 }}
              aria-label="Replay scrubber"
            />
            <Select
              size="small"
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              sx={{ minWidth: 70 }}
            >
              <MenuItem value={1}>1x</MenuItem>
              <MenuItem value={2}>2x</MenuItem>
              <MenuItem value={5}>5x</MenuItem>
            </Select>
          </Box>
        </Grid>

        <Grid item xs={12} md={3}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" sx={{ mb: 1 }}>
              At playhead
            </Typography>
            {state && (
              <Grid container spacing={1}>
                <Grid item xs={6}>
                  <Typography variant="caption" color="text.secondary">
                    Time
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography sx={{ fontVariantNumeric: "tabular-nums" }}>
                    {formatIstTime(new Date(state.time * 1000).toISOString())}
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="caption" color="text.secondary">
                    Open qty
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography sx={{ fontVariantNumeric: "tabular-nums" }}>{state.openQty}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="caption" color="text.secondary">
                    Unreal. R
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography color={state.unrealisedR >= 0 ? "success.main" : "error.main"}>
                    {formatR(state.unrealisedR)}
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="caption" color="text.secondary">
                    Stop
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography sx={{ fontVariantNumeric: "tabular-nums" }}>{state.currentStop}</Typography>
                </Grid>
                <Grid item xs={12}>
                  <Typography variant="caption" color="text.secondary">
                    Next event
                  </Typography>
                  <Typography variant="body2">
                    {state.nextEvent
                      ? `${state.nextEvent.kind} @ ${formatIstTime(
                          new Date(state.nextEvent.time * 1000).toISOString()
                        )}`
                      : "none remaining"}
                  </Typography>
                </Grid>
              </Grid>
            )}
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}
