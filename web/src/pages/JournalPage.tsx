import { useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import dayjs, { type Dayjs } from "dayjs";
import { DataGrid, type GridColDef, GridToolbar } from "@mui/x-data-grid";
import { useJournal } from "../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../components/StateBox";
import { formatR, formatIstTime } from "../lib/format";
import type { JournalRow } from "../api/types";

const columns: GridColDef<JournalRow>[] = [
  { field: "ts", headerName: "Time", width: 140, valueFormatter: (value) => formatIstTime(value as string) },
  { field: "symbol", headerName: "Symbol", width: 130 },
  { field: "strategy", headerName: "Strategy", width: 120 },
  { field: "exit_reason", headerName: "Exit", width: 100 },
  {
    field: "net_r",
    headerName: "Net R",
    width: 100,
    renderCell: (p) =>
      p.value === undefined ? (
        "—"
      ) : (
        <Box sx={{ color: (p.value as number) >= 0 ? "success.main" : "error.main" }}>
          {formatR(p.value as number)}
        </Box>
      ),
  },
];

export default function JournalPage() {
  const [from, setFrom] = useState<Dayjs | null>(dayjs().subtract(30, "day"));
  const [to, setTo] = useState<Dayjs | null>(dayjs());
  const journalQ = useJournal({
    from: from?.format("YYYY-MM-DD"),
    to: to?.format("YYYY-MM-DD"),
  });

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Journal
      </Typography>
      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <DatePicker label="From" value={from} onChange={setFrom} slotProps={{ textField: { size: "small" } }} />
        <DatePicker label="To" value={to} onChange={setTo} slotProps={{ textField: { size: "small" } }} />
      </Stack>
      {journalQ.isLoading && <LoadingBox label="" />}
      {journalQ.isError && <ErrorBox text="Couldn't load journal." />}
      {journalQ.data &&
        (journalQ.data.length === 0 ? (
          <EmptyBox text="No closed trades in this range." />
        ) : (
          <DataGrid
            autoHeight
            rows={journalQ.data}
            getRowId={(r) => r.signal_id}
            columns={columns}
            slots={{ toolbar: GridToolbar }}
            slotProps={{ toolbar: { csvOptions: { fileName: "journal" } } }}
          />
        ))}
    </Box>
  );
}
