import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Typography from "@mui/material/Typography";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { BarChart } from "@mui/x-charts/BarChart";
import { Gauge } from "@mui/x-charts/Gauge";
import { useTheme } from "@mui/material/styles";
import { EmptyBox } from "../StateBox";
import type { BacktestDetailResponse } from "../../api/types";

export default function DiagnosticsPanel({ detail }: { detail: BacktestDetailResponse }) {
  const theme = useTheme();
  const { diagnostics, metrics } = detail;

  if (!diagnostics) return <EmptyBox text="No diagnostics available for this run yet." />;

  const byHour = diagnostics.by_hour ?? [];
  const byExitReason = diagnostics.by_exit_reason ?? [];
  const mfeLosers = Object.values(diagnostics.mfe_losers_by_strategy ?? {}).flat();
  const rejections = diagnostics.rejections ?? [];
  const fillRate = metrics.fill_rate ?? 0;

  return (
    <Box>
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            By hour
          </Typography>
          {byHour.length === 0 ? (
            <EmptyBox text="No hourly breakdown available." />
          ) : (
            <BarChart
              height={180}
              series={[
                { data: byHour.map((h) => (h.avg_r < 0 ? h.trades : null)), color: theme.palette.error.main, stack: "h" },
                { data: byHour.map((h) => (h.avg_r >= 0 ? h.trades : null)), color: theme.palette.success.main, stack: "h" },
              ]}
              xAxis={[{ data: byHour.map((h) => `${h.hour}:00`), scaleType: "band" }]}
              slotProps={{ legend: { hidden: true } }}
            />
          )}
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            By exit reason
          </Typography>
          {byExitReason.length === 0 ? (
            <EmptyBox text="No exit-reason breakdown available." />
          ) : (
            <BarChart
              height={180}
              layout="horizontal"
              series={[{ data: byExitReason.map((e) => e.count), color: theme.palette.primary.main }]}
              yAxis={[{ data: byExitReason.map((e) => e.reason), scaleType: "band" }]}
            />
          )}
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            MFE — losers
          </Typography>
          {mfeLosers.length === 0 ? (
            <EmptyBox text="No losing trades yet." />
          ) : (
            <BarChart
              height={180}
              series={[{ data: mfeLosers, color: theme.palette.error.main }]}
              xAxis={[{ scaleType: "band", data: mfeLosers.map((_, i) => i) }]}
            />
          )}
        </Grid>
        <Grid item xs={12} md={3}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Fill rate
          </Typography>
          <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <Gauge width={140} height={140} value={Math.round(fillRate * 100)} text={`${Math.round(fillRate * 100)}%`} />
            <Typography variant="caption" color="text.secondary">
              Missed entries: {metrics.missed_entries ?? "—"}
            </Typography>
          </Box>
        </Grid>
        <Grid item xs={12} md={3}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Rejections
          </Typography>
          {rejections.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              None.
            </Typography>
          ) : (
            rejections.map((r) => (
              <Accordion key={r.reason} disableGutters>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="body2">
                    {r.reason} ({r.count})
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  {r.rows && r.rows.length > 0 ? (
                    <List dense>
                      {r.rows.map((row, i) => (
                        <ListItem key={i}>
                          <ListItemText primary={JSON.stringify(row)} />
                        </ListItem>
                      ))}
                    </List>
                  ) : (
                    <Typography variant="caption" color="text.secondary">
                      No detail rows returned.
                    </Typography>
                  )}
                </AccordionDetails>
              </Accordion>
            ))
          )}
        </Grid>
      </Grid>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: "block" }}>
        Expectancy (no slippage): {metrics.expectancy_r_no_slippage?.toFixed(2) ?? "—"} · Profit factor:{" "}
        {metrics.profit_factor?.toFixed(2) ?? "—"} · Max drawdown: {metrics.max_drawdown_r?.toFixed(1) ?? "—"}R
      </Typography>
    </Box>
  );
}
