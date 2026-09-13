import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Skeleton from "@mui/material/Skeleton";

export function LoadingBox({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        {label}
      </Typography>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={36} sx={{ mb: 0.5 }} />
      ))}
    </Box>
  );
}

export function EmptyBox({ text }: { text: string }) {
  return (
    <Box sx={{ py: 4, textAlign: "center" }}>
      <Typography variant="body1" color="text.secondary">
        {text}
      </Typography>
    </Box>
  );
}

export function ErrorBox({ text }: { text: string }) {
  return (
    <Box sx={{ py: 4, textAlign: "center" }}>
      <Typography variant="body1" color="error.main">
        {text}
      </Typography>
    </Box>
  );
}
