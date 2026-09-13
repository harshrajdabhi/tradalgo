import { useParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { BarChart } from "@mui/x-charts/BarChart";
import { useTheme } from "@mui/material/styles";
import { useSweepDetail } from "../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../components/StateBox";
import type { SweepCombo } from "../api/types";

export default function SweepDetailPage() {
  const { name } = useParams();
  const sweepQ = useSweepDetail(name ?? "");
  const theme = useTheme();

  const columns: GridColDef<SweepCombo>[] = [
    { field: "combo", headerName: "Combo", flex: 1 },
    {
      field: "train_r",
      headerName: "Train R",
      width: 100,
      renderCell: (p) => (
        <Box sx={{ color: (p.value as number) >= 0 ? "success.main" : "error.main" }}>
          {(p.value as number).toFixed(1)}
        </Box>
      ),
    },
    {
      field: "test_r",
      headerName: "Test R",
      width: 100,
      renderCell: (p) => (
        <Box sx={{ color: (p.value as number) >= 0 ? "success.main" : "error.main" }}>
          {(p.value as number).toFixed(1)}
        </Box>
      ),
    },
    { field: "delta", headerName: "Δ", width: 90, valueFormatter: (value) => (value as number).toFixed(1) },
    {
      field: "overfit",
      headerName: "Overfit?",
      width: 110,
      renderCell: (p) => (p.value ? "⚠ flagged" : "ok"),
    },
  ];

  if (sweepQ.isLoading) return <LoadingBox label="Loading sweep" />;
  if (sweepQ.isError || !sweepQ.data) return <ErrorBox text="Couldn't load this sweep." />;

  const d = sweepQ.data;
  const combos = d.combos ?? [];

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Sweep {name}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {d.train && `Train ${d.train.from} → ${d.train.to} · `}
        {d.test && `Test ${d.test.from} → ${d.test.to} · `}
        {d.total_combinations} combos · {d.verdict}
      </Typography>

      {combos.length === 0 ? (
        <EmptyBox text="No combo results in this sweep." />
      ) : (
        <>
          <BarChart
            height={220}
            series={[
              { data: combos.map((c) => c.train_r), label: "Train R", color: theme.palette.text.primary },
              { data: combos.map((c) => c.test_r), label: "Test R", color: theme.palette.mode === "light" ? "#2E5C8A" : "#6FA0D6" },
            ]}
            xAxis={[{ data: combos.map((c) => c.combo), scaleType: "band" }]}
            sx={{ mb: 3 }}
          />

          <DataGrid
            autoHeight
            rows={combos}
            getRowId={(r) => r.combo}
            columns={columns}
            getRowClassName={(p) => (p.row.overfit ? "flagged-row" : "")}
            sx={{
              "& .flagged-row": {
                borderLeft: `3px solid ${theme.palette.warning.main}`,
              },
            }}
          />
        </>
      )}

      {d.recommended_yaml && (
        <Paper sx={{ p: 2, mt: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Recommended config
          </Typography>
          <Box
            component="pre"
            sx={{
              bgcolor: "background.default",
              p: 2,
              overflow: "auto",
              fontSize: 13,
              fontFamily: "monospace",
            }}
          >
            {d.recommended_yaml}
          </Box>
        </Paper>
      )}
    </Box>
  );
}
