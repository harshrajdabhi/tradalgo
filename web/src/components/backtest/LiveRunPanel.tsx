import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import { LineChart } from "@mui/x-charts/LineChart";
import { BarChart } from "@mui/x-charts/BarChart";
import { useTheme } from "@mui/material/styles";
import { LoadingBox, EmptyBox } from "../StateBox";
import { formatR, formatPercent } from "../../lib/format";
import type { BacktestLiveResponse } from "../../api/types";

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Paper sx={{ p: 2, textAlign: "center" }}>
      <Typography variant="h5" sx={{ fontVariantNumeric: "tabular-nums" }}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Paper>
  );
}

export default function LiveRunPanel({
  data,
  loading,
}: {
  data?: BacktestLiveResponse;
  loading: boolean;
}) {
  const theme = useTheme();
  if (loading && !data) return <LoadingBox label="Loading live run" rows={6} />;
  if (!data) return <EmptyBox text="No live data yet." />;

  return (
    <Box>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} sm={3}>
          <Kpi label="Trades so far" value={String(data.trades_so_far)} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <Kpi label="Expectancy R" value={formatR(data.expectancy_r)} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <Kpi label="Win rate" value={formatPercent(data.win_rate)} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <Kpi label="Net R" value={formatR(data.net_r)} />
        </Grid>
      </Grid>

      <Typography variant="h6" sx={{ mb: 1 }}>
        Equity curve
      </Typography>
      <LineChart
        height={220}
        series={[
          {
            data: data.equity_curve.map((p) => p.cum_net_r),
            color: theme.palette.mode === "light" ? "#2E5C8A" : "#6FA0D6",
            showMark: false,
          },
        ]}
        xAxis={[{ data: data.equity_curve.map((p) => p.trade_index), scaleType: "point" }]}
        sx={{ mb: 3 }}
      />

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            R-multiple histogram
          </Typography>
          <BarChart
            height={200}
            series={[
              {
                data: data.r_histogram.map((b) => (b.bin_start < 0 ? b.count : null)),
                color: theme.palette.error.main,
                stack: "r",
              },
              {
                data: data.r_histogram.map((b) => (b.bin_start >= 0 ? b.count : null)),
                color: theme.palette.success.main,
                stack: "r",
              },
            ]}
            xAxis={[
              {
                data: data.r_histogram.map((b) => `${b.bin_start}R`),
                scaleType: "band",
              },
            ]}
            slotProps={{ legend: { hidden: true } }}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            By strategy (updating)
          </Typography>
          <List dense>
            {data.by_strategy.map((v) => (
              <ListItem key={v.strategy} divider>
                <ListItemText primary={v.strategy} secondary={`${v.trades} trades`} />
                <Typography color={v.expectancy_r >= 0 ? "success.main" : "error.main"}>
                  {formatR(v.expectancy_r)}
                </Typography>
              </ListItem>
            ))}
          </List>
        </Grid>
      </Grid>

      <Typography variant="h6" sx={{ mt: 3, mb: 1 }}>
        Latest trades
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {data.latest_trades
          .map((t) => {
            const r = t as { time?: string; symbol?: string; net_r?: number; exit_ts?: string };
            const label = r.time ?? r.exit_ts ?? "";
            return `${label} ${r.symbol ?? ""} ${r.net_r !== undefined ? formatR(r.net_r) : ""}`;
          })
          .join(" · ")}
      </Typography>
    </Box>
  );
}
