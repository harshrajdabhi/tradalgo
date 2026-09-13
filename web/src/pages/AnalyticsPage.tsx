import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Typography from "@mui/material/Typography";
import { BarChart } from "@mui/x-charts/BarChart";
import { ScatterChart } from "@mui/x-charts/ScatterChart";
import { useTheme } from "@mui/material/styles";
import { useAnalytics } from "../api/hooks";
import { ErrorBox, LoadingBox } from "../components/StateBox";

export default function AnalyticsPage() {
  const analyticsQ = useAnalytics();
  const theme = useTheme();

  if (analyticsQ.isLoading) return <LoadingBox label="Loading analytics" />;
  if (analyticsQ.isError || !analyticsQ.data) return <ErrorBox text="Couldn't load analytics." />;

  const d = analyticsQ.data;
  const accent = theme.palette.mode === "light" ? "#2E5C8A" : "#6FA0D6";

  // R-multiple bars follow the app-wide rule: color by sign, never by
  // category. A single series can't mix colors per bar, so split each
  // expectancy series into a loss half and a gain half stacked at the
  // same positions (the other half is null so only one segment renders).
  function signSplit(values: number[]) {
    return {
      loss: values.map((v) => (v < 0 ? v : null)),
      gain: values.map((v) => (v >= 0 ? v : null)),
    };
  }

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Analytics
      </Typography>
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Expectancy by strategy
          </Typography>
          <BarChart
            height={220}
            series={[
              { data: signSplit(d.expectancy_by_strategy.map((s) => s.expectancy_r)).loss, color: theme.palette.error.main, stack: "r" },
              { data: signSplit(d.expectancy_by_strategy.map((s) => s.expectancy_r)).gain, color: theme.palette.success.main, stack: "r" },
            ]}
            xAxis={[{ data: d.expectancy_by_strategy.map((s) => s.grp), scaleType: "band" }]}
            slotProps={{ legend: { hidden: true } }}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Expectancy by regime
          </Typography>
          <BarChart
            height={220}
            series={[
              { data: signSplit(d.expectancy_by_regime.map((s) => s.expectancy_r)).loss, color: theme.palette.error.main, stack: "r" },
              { data: signSplit(d.expectancy_by_regime.map((s) => s.expectancy_r)).gain, color: theme.palette.success.main, stack: "r" },
            ]}
            xAxis={[{ data: d.expectancy_by_regime.map((s) => s.grp), scaleType: "band" }]}
            slotProps={{ legend: { hidden: true } }}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Expectancy by hour
          </Typography>
          <BarChart
            height={220}
            series={[
              { data: signSplit(d.expectancy_by_hour.map((s) => s.expectancy_r)).loss, color: theme.palette.error.main, stack: "r" },
              { data: signSplit(d.expectancy_by_hour.map((s) => s.expectancy_r)).gain, color: theme.palette.success.main, stack: "r" },
            ]}
            xAxis={[{ data: d.expectancy_by_hour.map((s) => `${s.grp}:00`), scaleType: "band" }]}
            slotProps={{ legend: { hidden: true } }}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Expectancy by symbol
          </Typography>
          <BarChart
            height={220}
            series={[
              { data: signSplit(d.expectancy_by_symbol.map((s) => s.expectancy_r)).loss, color: theme.palette.error.main, stack: "r" },
              { data: signSplit(d.expectancy_by_symbol.map((s) => s.expectancy_r)).gain, color: theme.palette.success.main, stack: "r" },
            ]}
            xAxis={[{ data: d.expectancy_by_symbol.map((s) => s.grp), scaleType: "band" }]}
            slotProps={{ legend: { hidden: true } }}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            MFE vs MAE
          </Typography>
          <ScatterChart
            height={220}
            series={[
              {
                data: d.mfe_mae_points.map((p, i) => ({ id: i, x: p.mfe_r, y: p.mae_r })),
                color: accent,
              },
            ]}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Live vs backtest
          </Typography>
          <BarChart
            height={220}
            series={[
              { data: d.live_vs_backtest.map((p) => p.backtest_expectancy_r), label: "Backtest R", color: theme.palette.text.secondary },
              { data: d.live_vs_backtest.map((p) => p.live_expectancy_r), label: "Live R", color: accent },
            ]}
            xAxis={[{ data: d.live_vs_backtest.map((p) => p.strategy), scaleType: "band" }]}
          />
        </Grid>
      </Grid>
    </Box>
  );
}
