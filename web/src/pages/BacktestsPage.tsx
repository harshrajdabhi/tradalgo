import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import Grid from "@mui/material/Grid";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Button from "@mui/material/Button";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { useBacktests, useQueueBacktest } from "../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../components/StateBox";
import type { BacktestParams, BacktestRun } from "../api/types";

const STRATEGIES = ["orb", "vwap-rev"];

export default function BacktestsPage() {
  const navigate = useNavigate();
  const backtestsQ = useBacktests();
  const queue = useQueueBacktest();

  const [form, setForm] = useState<BacktestParams>({
    from: "2026-01-01",
    to: "2026-06-30",
    universe: "nifty50",
    strategies: ["orb"],
    shortlist_size: 6,
    slippage_pct: 0.05,
    max_risk_pct: 0.01,
    initial_capital: 500000,
  });
  const [formError, setFormError] = useState<string | null>(null);

  function validate(): string | null {
    if (form.to < form.from) return "Can't queue this backtest: end date is before start date.";
    if (form.shortlist_size < 5 || form.shortlist_size > 7) return "Shortlist size must be between 5 and 7.";
    if (form.max_risk_pct > 0.03) return "Max risk per trade must be at most 3%.";
    if (form.strategies.length === 0) return "Select at least one strategy.";
    return null;
  }

  function submit() {
    const err = validate();
    if (err) {
      setFormError(err);
      return;
    }
    setFormError(null);
    queue.mutate(form, {
      onSuccess: (res) => navigate(`/backtests/${res.id}`),
      onError: (e: unknown) => setFormError((e as Error).message),
    });
  }

  function parseParams(run: BacktestRun): Partial<BacktestParams> {
    try {
      return run.params_json ? JSON.parse(run.params_json) : {};
    } catch {
      return {};
    }
  }
  function parseMetrics(run: BacktestRun): { net_r?: number } {
    try {
      return run.metrics_json ? JSON.parse(run.metrics_json) : {};
    } catch {
      return {};
    }
  }

  const columns: GridColDef<BacktestRun>[] = [
    { field: "id", headerName: "ID", width: 70 },
    {
      field: "from",
      headerName: "From",
      width: 110,
      valueGetter: (_v, row) => parseParams(row).from ?? "—",
    },
    {
      field: "to",
      headerName: "To",
      width: 110,
      valueGetter: (_v, row) => parseParams(row).to ?? "—",
    },
    {
      field: "universe",
      headerName: "Universe",
      width: 110,
      valueGetter: (_v, row) => parseParams(row).universe ?? "—",
    },
    {
      field: "strategies",
      headerName: "Strategies",
      flex: 1,
      valueGetter: (_v, row) => (parseParams(row).strategies ?? []).join(", "),
    },
    { field: "status", headerName: "Status", width: 110 },
    { field: "progress_pct", headerName: "Progress", width: 100, valueFormatter: (value) => (value !== undefined ? `${value}%` : "—") },
    {
      field: "net_r",
      headerName: "Net R",
      width: 90,
      valueGetter: (_v, row) => parseMetrics(row).net_r,
      renderCell: (p) =>
        p.value === undefined ? "—" : (
          <Typography color={(p.value as number) >= 0 ? "success.main" : "error.main"}>
            {(p.value as number).toFixed(1)}
          </Typography>
        ),
    },
  ];

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Backtests
      </Typography>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Queue a backtest
        </Typography>
        <Grid container spacing={2}>
          <Grid item xs={6} sm={3}>
            <TextField
              label="From"
              type="date"
              fullWidth
              size="small"
              InputLabelProps={{ shrink: true }}
              value={form.from}
              onChange={(e) => setForm({ ...form, from: e.target.value })}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              label="To"
              type="date"
              fullWidth
              size="small"
              InputLabelProps={{ shrink: true }}
              value={form.to}
              onChange={(e) => setForm({ ...form, to: e.target.value })}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              select
              label="Universe"
              fullWidth
              size="small"
              value={form.universe}
              onChange={(e) => setForm({ ...form, universe: e.target.value as BacktestParams["universe"] })}
            >
              <MenuItem value="nifty50">Nifty 50</MenuItem>
              <MenuItem value="niftynext50">Nifty Next 50</MenuItem>
              <MenuItem value="both">Both</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              select
              label="Strategies"
              fullWidth
              size="small"
              SelectProps={{ multiple: true }}
              value={form.strategies}
              onChange={(e) =>
                setForm({ ...form, strategies: e.target.value as unknown as string[] })
              }
            >
              {STRATEGIES.map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              label="Shortlist size"
              type="number"
              fullWidth
              size="small"
              value={form.shortlist_size}
              onChange={(e) => setForm({ ...form, shortlist_size: Number(e.target.value) })}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              label="Slippage %"
              type="number"
              fullWidth
              size="small"
              value={form.slippage_pct}
              onChange={(e) => setForm({ ...form, slippage_pct: Number(e.target.value) })}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              label="Max risk %"
              type="number"
              fullWidth
              size="small"
              value={form.max_risk_pct}
              onChange={(e) => setForm({ ...form, max_risk_pct: Number(e.target.value) })}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              label="Initial capital"
              type="number"
              fullWidth
              size="small"
              value={form.initial_capital}
              onChange={(e) => setForm({ ...form, initial_capital: Number(e.target.value) })}
            />
          </Grid>
        </Grid>
        {formError && (
          <Typography color="error.main" sx={{ mt: 2 }}>
            {formError}
          </Typography>
        )}
        <Button variant="contained" sx={{ mt: 2 }} onClick={submit} disabled={queue.isPending}>
          Queue backtest
        </Button>
      </Paper>

      {backtestsQ.isLoading && <LoadingBox label="" />}
      {backtestsQ.isError && <ErrorBox text="Couldn't load backtests." />}
      {backtestsQ.data &&
        (backtestsQ.data.length === 0 ? (
          <EmptyBox text="No backtests yet. Queue one above to see results here." />
        ) : (
          <DataGrid
            autoHeight
            rows={backtestsQ.data}
            columns={columns}
            onRowClick={(p) => navigate(`/backtests/${p.id}`)}
            sx={{ cursor: "pointer" }}
          />
        ))}
    </Box>
  );
}
