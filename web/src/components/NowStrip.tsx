import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import type { NowResponse } from "../api/types";
import { nowStripView } from "../lib/nowStrip";

export default function NowStrip({ now }: { now: NowResponse }) {
  const view = nowStripView(now);
  return (
    <Alert
      severity={view.severity === "warning" ? "warning" : "info"}
      icon={false}
      sx={{
        bgcolor: "background.paper",
        borderLeftColor: view.severity === "warning" ? "warning.main" : "text.secondary",
        color: view.severity === "warning" ? "text.primary" : "text.secondary",
        mb: 3,
        "& .MuiAlert-message": { width: "100%" },
      }}
    >
      <Typography variant="body1" sx={{ fontWeight: view.severity === "warning" ? 600 : 400 }}>
        {view.headline}
      </Typography>
    </Alert>
  );
}
