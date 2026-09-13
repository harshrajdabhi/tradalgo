import { useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import { useSweeps } from "../api/hooks";
import { EmptyBox, ErrorBox, LoadingBox } from "../components/StateBox";

export default function SweepsPage() {
  const sweepsQ = useSweeps();
  const navigate = useNavigate();

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Sweeps
      </Typography>
      {sweepsQ.isLoading && <LoadingBox label="" />}
      {sweepsQ.isError && <ErrorBox text="Couldn't load sweeps." />}
      {sweepsQ.data &&
        (sweepsQ.data.length === 0 ? (
          <EmptyBox text="No sweeps yet. Run one from the command line, then results appear here." />
        ) : (
          <List>
            {sweepsQ.data.map((s) => (
              <ListItemButton key={s.name} onClick={() => navigate(`/sweeps/${s.name}`)} divider>
                <ListItemText primary={s.name} secondary={`${s.verdict} · generated ${s.generated_at}`} />
              </ListItemButton>
            ))}
          </List>
        ))}
    </Box>
  );
}
