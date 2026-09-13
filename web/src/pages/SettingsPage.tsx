import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import Grid from "@mui/material/Grid";
import TextField from "@mui/material/TextField";
import Switch from "@mui/material/Switch";
import FormControlLabel from "@mui/material/FormControlLabel";
import Button from "@mui/material/Button";
import Snackbar from "@mui/material/Snackbar";
import Alert from "@mui/material/Alert";
import { useSettings, usePutSettings, useKillSwitch, useHealth } from "../api/hooks";
import { ErrorBox, LoadingBox } from "../components/StateBox";

export default function SettingsPage() {
  const settingsQ = useSettings();
  const putSettings = usePutSettings();
  const healthQ = useHealth();
  const killSwitch = useKillSwitch();

  const [form, setForm] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (settingsQ.data) setForm(settingsQ.data);
  }, [settingsQ.data]);

  function save() {
    setError(null);
    putSettings.mutate(form, {
      onSuccess: (res) => setSaved(res.backup ? `Saved. Backup at ${res.backup}.` : "Saved."),
      onError: (e: unknown) => setError((e as Error).message),
    });
  }

  if (settingsQ.isLoading) return <LoadingBox label="Loading settings" />;
  if (settingsQ.isError) return <ErrorBox text="Couldn't load settings." />;

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Settings
      </Typography>

      <Paper sx={{ p: 2, mb: 3 }}>
        <FormControlLabel
          control={
            <Switch
              checked={!!healthQ.data?.kill_switch}
              onChange={(e) => killSwitch.mutate(e.target.checked)}
              color="error"
            />
          }
          label="Kill switch (stop new alerts)"
        />
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Grid container spacing={2}>
          <Grid item xs={6} sm={4}>
            <TextField
              label="Max risk %"
              type="number"
              size="small"
              fullWidth
              value={form.max_risk_pct ?? ""}
              onChange={(e) => setForm({ ...form, max_risk_pct: Number(e.target.value) })}
            />
          </Grid>
          <Grid item xs={6} sm={4}>
            <TextField
              label="Shortlist size"
              type="number"
              size="small"
              fullWidth
              value={form.shortlist_size ?? ""}
              onChange={(e) => setForm({ ...form, shortlist_size: Number(e.target.value) })}
            />
          </Grid>
          <Grid item xs={6} sm={4}>
            <TextField
              label="Slippage %"
              type="number"
              size="small"
              fullWidth
              value={form.slippage_pct ?? ""}
              onChange={(e) => setForm({ ...form, slippage_pct: Number(e.target.value) })}
            />
          </Grid>
        </Grid>
        {error && (
          <Typography color="error.main" sx={{ mt: 2 }}>
            {error}
          </Typography>
        )}
        <Button variant="contained" sx={{ mt: 2 }} onClick={save} disabled={putSettings.isPending}>
          Save settings
        </Button>
      </Paper>

      <Snackbar open={!!saved} autoHideDuration={4000} onClose={() => setSaved(null)}>
        {saved ? (
          <Alert severity="success" onClose={() => setSaved(null)}>
            {saved}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Box>
  );
}
