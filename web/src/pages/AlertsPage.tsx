import { useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Snackbar from "@mui/material/Snackbar";
import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { useAlerts, useResendAlert } from "../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../components/StateBox";
import type { Alert as AlertRow } from "../api/types";
import { formatIstTime } from "../lib/format";

export default function AlertsPage() {
  const alertsQ = useAlerts();
  const resend = useResendAlert();
  const [snack, setSnack] = useState<{ msg: string; ok: boolean } | null>(null);

  const columns: GridColDef<AlertRow>[] = [
    {
      field: "created_at",
      headerName: "Time",
      width: 90,
      valueFormatter: (value) => formatIstTime(value as string),
    },
    { field: "symbol", headerName: "Symbol", width: 130 },
    { field: "text", headerName: "Message", flex: 1 },
    {
      field: "status",
      headerName: "Status",
      width: 130,
      renderCell: (params) => {
        const s = params.value as AlertRow["status"];
        const color = s === "sent" ? "success" : s === "failed" ? "error" : "warning";
        return <Chip size="small" label={s} color={color} variant={s === "sent" ? "outlined" : "filled"} />;
      },
    },
    {
      field: "actions",
      headerName: "",
      width: 120,
      sortable: false,
      renderCell: (params) => {
        if (params.row.status !== "failed") return null;
        return (
          <Button
            size="small"
            onClick={() =>
              resend.mutate(params.row.alert_id, {
                onSuccess: () => setSnack({ msg: `Resent alert for ${params.row.symbol}.`, ok: true }),
                onError: (e: unknown) =>
                  setSnack({ msg: `Resend failed: ${(e as Error).message}. Try again in a moment.`, ok: false }),
              })
            }
          >
            Resend
          </Button>
        );
      },
    },
  ];

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Alerts
      </Typography>
      {alertsQ.isLoading && <LoadingBox label="" />}
      {alertsQ.isError && <ErrorBox text="Couldn't load alerts." />}
      {alertsQ.data && (
        <>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <Chip variant="outlined" label={`Sent ${alertsQ.data.counts.sent}`} />
            <Chip color="error" label={`Failed ${alertsQ.data.counts.failed}`} />
            <Chip color="warning" label={`Awaiting ${alertsQ.data.counts.awaiting}`} />
          </Stack>
          {alertsQ.data.alerts.length === 0 ? (
            <EmptyBox text="No alerts in this range." />
          ) : (
            <DataGrid
              autoHeight
              rows={alertsQ.data.alerts}
              getRowId={(r) => r.alert_id}
              columns={columns}
              disableRowSelectionOnClick
            />
          )}
        </>
      )}
      <Snackbar open={!!snack} autoHideDuration={4000} onClose={() => setSnack(null)}>
        {snack ? (
          <Alert severity={snack.ok ? "success" : "error"} onClose={() => setSnack(null)}>
            {snack.msg}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Box>
  );
}
