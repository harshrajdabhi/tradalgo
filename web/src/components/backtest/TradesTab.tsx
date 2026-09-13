import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import { DataGrid, type GridColDef, GridToolbar } from "@mui/x-data-grid";
import { useBacktestTrades } from "../../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../StateBox";
import { formatR } from "../../lib/format";
import type { Trade } from "../../api/types";

export default function TradesTab({
  backtestId,
  onOpenReplay,
}: {
  backtestId: number;
  onOpenReplay: (tradeId: string) => void;
}) {
  const tradesQ = useBacktestTrades(backtestId);

  const columns: GridColDef<Trade>[] = [
    { field: "trade_date", headerName: "Date", width: 110 },
    { field: "symbol", headerName: "Symbol", width: 130 },
    { field: "strategy", headerName: "Strategy", width: 120 },
    { field: "exit_reason", headerName: "Exit", width: 100 },
    {
      field: "net_r",
      headerName: "Net R",
      width: 90,
      renderCell: (p) => (
        <Box sx={{ color: (p.value as number) >= 0 ? "success.main" : "error.main" }}>
          {formatR(p.value as number)}
        </Box>
      ),
    },
    {
      field: "replay",
      headerName: "",
      width: 100,
      sortable: false,
      renderCell: (p) => (
        <Button size="small" onClick={() => onOpenReplay(String(p.row.id))}>
          Replay
        </Button>
      ),
    },
  ];

  if (tradesQ.isLoading) return <LoadingBox label="Loading trades" />;
  if (tradesQ.isError) return <ErrorBox text="Couldn't load trades." />;
  if (!tradesQ.data || tradesQ.data.length === 0) return <EmptyBox text="No trades in this run." />;

  return (
    <DataGrid
      autoHeight
      rows={tradesQ.data}
      getRowId={(r) => r.id}
      columns={columns}
      slots={{ toolbar: GridToolbar }}
      slotProps={{ toolbar: { csvOptions: { fileName: `backtest-${backtestId}-trades` } } }}
    />
  );
}
