import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import { useBacktestDetail, useBacktestLive } from "../api/hooks";
import { ErrorBox, LoadingBox } from "../components/StateBox";
import LiveRunPanel from "../components/backtest/LiveRunPanel";
import TradesTab from "../components/backtest/TradesTab";
import DiagnosticsPanel from "../components/backtest/DiagnosticsPanel";
import ReplayView from "../components/backtest/ReplayView";
import { gateVerdictText } from "../lib/format";

export default function BacktestDetailPage() {
  const { id } = useParams();
  const backtestId = Number(id);
  const detailQ = useBacktestDetail(backtestId);
  const liveQ = useBacktestLive(backtestId, detailQ.data?.run.status);
  const [tab, setTab] = useState<string | null>(null);
  const [replayTradeId, setReplayTradeId] = useState<string | null>(null);

  const status = liveQ.data?.status ?? detailQ.data?.run.status;
  const running = status === "running" || status === "queued";

  useEffect(() => {
    if (tab === null && status) {
      setTab(running ? "live" : "diagnostics");
    }
  }, [status, running, tab]);

  if (detailQ.isLoading) return <LoadingBox label="Loading run" />;
  if (detailQ.isError || !detailQ.data) return <ErrorBox text="Couldn't load this backtest." />;

  const { run, gate, params } = detailQ.data;

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", mb: 1 }}>
        <Typography variant="h5">
          Backtest #{run.id} {params ? `${params.from} → ${params.to}` : ""}
        </Typography>
        {running ? (
          <Chip
            size="small"
            label={`● running ${liveQ.data?.progress_pct ?? 0}%`}
            sx={{
              animation: "pulse 1.6s ease infinite",
              "@keyframes pulse": { "0%,100%": { opacity: 1 }, "50%": { opacity: 0.5 } },
              "@media (prefers-reduced-motion: reduce)": { animation: "none" },
            }}
            color="default"
          />
        ) : (
          <Chip
            size="small"
            color={gate.passed ? "success" : "error"}
            label={gateVerdictText(gate.passed, gate.reason)}
          />
        )}
      </Box>
      {running && (
        <LinearProgress variant="determinate" value={liveQ.data?.progress_pct ?? 0} sx={{ mb: 2 }} />
      )}

      <Tabs value={tab ?? "live"} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="live" label="Live" />
        <Tab value="trades" label="Trades" />
        <Tab value="replay" label="Replay" />
        <Tab value="diagnostics" label="Diagnostics" />
      </Tabs>

      {tab === "live" && <LiveRunPanel data={liveQ.data} loading={liveQ.isLoading} />}
      {tab === "trades" && (
        <TradesTab
          backtestId={backtestId}
          onOpenReplay={(tradeId) => {
            setReplayTradeId(tradeId);
            setTab("replay");
          }}
        />
      )}
      {tab === "replay" && (
        <ReplayView
          backtestId={backtestId}
          initialTradeId={replayTradeId}
          onExit={() => setTab("trades")}
        />
      )}
      {tab === "diagnostics" && <DiagnosticsPanel detail={detailQ.data} />}
    </Box>
  );
}
