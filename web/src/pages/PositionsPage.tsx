import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import { usePositions } from "../api/hooks";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import MiniCandleChart from "../components/MiniCandleChart";
import { LoadingBox, EmptyBox, ErrorBox } from "../components/StateBox";
import { formatR } from "../lib/format";
import type { Position } from "../api/types";

function unrealisedR(position: Position, lastClose: number | null): number | null {
  if (lastClose === null) return null;
  const risk = Math.abs(position.entry_price - position.stop_loss);
  if (risk === 0) return null;
  const direction = position.direction === "short" ? -1 : 1;
  return ((lastClose - position.entry_price) / risk) * direction;
}

function PositionCard({ position }: { position: Position }) {
  const candlesQ = useQuery({
    queryKey: ["candles", position.symbol],
    queryFn: () => api.candles(position.symbol),
  });
  const lastClose = candlesQ.data?.candles.length
    ? candlesQ.data.candles[candlesQ.data.candles.length - 1].close
    : null;
  const r = unrealisedR(position, lastClose);
  const gain = (r ?? 0) >= 0;

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Box sx={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 1 }}>
          <Typography variant="h6">{position.symbol}</Typography>
          <Typography sx={{ fontVariantNumeric: "tabular-nums" }} color="text.secondary">
            qty {position.qty} · entry {position.entry_price.toLocaleString("en-IN")} · stop{" "}
            {position.stop_loss.toLocaleString("en-IN")}
          </Typography>
          <Typography
            sx={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}
            color={gain ? "success.main" : "error.main"}
          >
            {r === null ? "—" : formatR(r)}
          </Typography>
        </Box>
        <Box sx={{ mt: 1 }}>
          {candlesQ.isLoading && <LoadingBox label="" rows={1} />}
          {candlesQ.data && (
            <MiniCandleChart
              candles={candlesQ.data.candles}
              vwap={candlesQ.data.session_vwap}
              levels={{ entry: position.entry_price, stop: position.stop_loss }}
            />
          )}
        </Box>
      </CardContent>
    </Card>
  );
}

export default function PositionsPage() {
  const positionsQ = usePositions();

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Positions
      </Typography>
      {positionsQ.isLoading && <LoadingBox label="" />}
      {positionsQ.isError && <ErrorBox text="Couldn't load positions." />}
      {positionsQ.data &&
        (positionsQ.data.length === 0 ? (
          <EmptyBox text="No open positions right now." />
        ) : (
          positionsQ.data.map((p) => <PositionCard key={p.trade_id} position={p} />)
        ))}
    </Box>
  );
}
