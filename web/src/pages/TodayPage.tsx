import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Grid from "@mui/material/Grid";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Switch from "@mui/material/Switch";
import FormControlLabel from "@mui/material/FormControlLabel";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { useNow, useShortlist, useSignals, useHealth, useKillSwitch } from "../api/hooks";
import NowStrip from "../components/NowStrip";
import { LoadingBox, EmptyBox, ErrorBox } from "../components/StateBox";
import { formatIstTime } from "../lib/format";
import type { ShortlistRow, SignalRow } from "../api/types";

const shortlistCols: GridColDef<ShortlistRow>[] = [
  { field: "rank", headerName: "#", width: 50 },
  { field: "symbol", headerName: "Symbol", flex: 1 },
  {
    field: "composite_score",
    headerName: "Score",
    width: 160,
    renderCell: (params) => (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, width: "100%" }}>
        <Typography variant="body2" sx={{ fontVariantNumeric: "tabular-nums", width: 24 }}>
          {params.value}
        </Typography>
        <Box sx={{ flexGrow: 1, height: 6, bgcolor: "divider" }}>
          <Box sx={{ width: `${params.value}%`, height: "100%", bgcolor: "text.primary" }} />
        </Box>
      </Box>
    ),
  },
  { field: "reasons", headerName: "Reasons", flex: 1 },
];

function SignalFeed({ rows }: { rows: SignalRow[] }) {
  if (rows.length === 0) return <EmptyBox text="No signals yet today." />;
  const sorted = [...rows].sort((a, b) => (a.ts < b.ts ? 1 : -1));
  return (
    <List dense>
      {sorted.map((r) => (
        <ListItem key={r.signal_id} divider>
          <ListItemText
            primary={`${r.accepted ? "▲" : "—"} ${formatIstTime(r.ts)}  ${r.symbol}`}
            secondary={r.rejection_reason ?? r.strategy}
            primaryTypographyProps={{ sx: { fontVariantNumeric: "tabular-nums" } }}
          />
        </ListItem>
      ))}
    </List>
  );
}

export default function TodayPage() {
  const nowQ = useNow();
  const shortlistQ = useShortlist();
  const signalsQ = useSignals();
  const healthQ = useHealth();
  const killSwitch = useKillSwitch();

  return (
    <Box>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography variant="h5">Today</Typography>
        <FormControlLabel
          control={
            <Switch
              checked={!!healthQ.data?.kill_switch}
              onChange={(e) => killSwitch.mutate(e.target.checked)}
              color="error"
            />
          }
          label="Kill switch"
        />
      </Box>

      {nowQ.isLoading && <LoadingBox label="Now" rows={1} />}
      {nowQ.isError && <ErrorBox text="Couldn't load status." />}
      {nowQ.data && <NowStrip now={nowQ.data} />}

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Shortlist
          </Typography>
          {shortlistQ.isLoading && <LoadingBox label="" />}
          {shortlistQ.isError && <ErrorBox text="Couldn't load shortlist." />}
          {shortlistQ.data &&
            (shortlistQ.data.length === 0 ? (
              <EmptyBox text="No shortlist for today yet." />
            ) : (
              <DataGrid
                autoHeight
                rows={shortlistQ.data}
                getRowId={(r) => r.symbol}
                columns={shortlistCols}
                hideFooter
                disableRowSelectionOnClick
              />
            ))}
        </Grid>
        <Grid item xs={12} md={6}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Signals
          </Typography>
          {signalsQ.isLoading && <LoadingBox label="" />}
          {signalsQ.isError && <ErrorBox text="Couldn't load signals." />}
          {signalsQ.data && <SignalFeed rows={signalsQ.data} />}
        </Grid>
      </Grid>
    </Box>
  );
}
