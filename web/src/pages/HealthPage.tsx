import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import { useHealth, useJobs } from "../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../components/StateBox";

function rowLabel(row: Record<string, unknown>): string {
  const primary = row.name ?? row.job ?? row.kind ?? row.event ?? "event";
  return String(primary);
}
function rowDetail(row: Record<string, unknown>): string {
  const parts = Object.entries(row)
    .filter(([k]) => !["name", "job", "kind", "event"].includes(k))
    .map(([k, v]) => `${k}: ${v}`);
  return parts.join(" · ");
}

function RecordList({ rows, empty }: { rows: Record<string, unknown>[]; empty: string }) {
  if (rows.length === 0) return <EmptyBox text={empty} />;
  return (
    <List dense sx={{ mb: 3 }}>
      {rows.map((r, i) => (
        <ListItem key={i} divider>
          <ListItemText primary={rowLabel(r)} secondary={rowDetail(r)} />
        </ListItem>
      ))}
    </List>
  );
}

export default function HealthPage() {
  const healthQ = useHealth();
  const jobsQ = useJobs();

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Health
      </Typography>
      {healthQ.isLoading && <LoadingBox label="" rows={2} />}
      {healthQ.isError && <ErrorBox text="Couldn't load health." />}
      {healthQ.data && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={6} sm={3}>
            <Paper sx={{ p: 2, textAlign: "center" }}>
              <Typography variant="h6">{healthQ.data.ok ? "OK" : "Degraded"}</Typography>
              <Typography variant="caption" color="text.secondary">
                System status
              </Typography>
            </Paper>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Paper sx={{ p: 2, textAlign: "center" }}>
              <Typography variant="h6">{healthQ.data.market_open ? "Open" : "Closed"}</Typography>
              <Typography variant="caption" color="text.secondary">
                Market
              </Typography>
            </Paper>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Paper sx={{ p: 2, textAlign: "center" }}>
              <Typography variant="h6">{healthQ.data.kill_switch ? "ON" : "off"}</Typography>
              <Typography variant="caption" color="text.secondary">
                Kill switch
              </Typography>
            </Paper>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Paper sx={{ p: 2, textAlign: "center" }}>
              <Typography variant="body1" sx={{ fontVariantNumeric: "tabular-nums" }}>
                {healthQ.data.fyers_token_expiry ?? "unknown"}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Token expiry
              </Typography>
            </Paper>
          </Grid>
        </Grid>
      )}

      <Typography variant="h6" sx={{ mb: 1 }}>
        Job runs
      </Typography>
      {jobsQ.isLoading && <LoadingBox label="" />}
      {jobsQ.isError && <ErrorBox text="Couldn't load jobs." />}
      {jobsQ.data && (
        <>
          <RecordList rows={jobsQ.data.job_runs} empty="No job runs recorded." />
          <Typography variant="h6" sx={{ mb: 1 }}>
            Health events
          </Typography>
          <RecordList rows={jobsQ.data.health_events} empty="No health events recorded." />
          <Typography variant="h6" sx={{ mb: 1 }}>
            Degraded periods (data)
          </Typography>
          <RecordList rows={jobsQ.data.degraded_data} empty="No degraded data periods recorded." />
          <Typography variant="h6" sx={{ mb: 1 }}>
            Degraded periods (socket)
          </Typography>
          <RecordList rows={jobsQ.data.degraded_socket} empty="No degraded socket periods recorded." />
        </>
      )}
    </Box>
  );
}
