import type { NowResponse } from "../api/types";

export interface NowStripView {
  severity: "warning" | "quiet";
  headline: string;
}

export function nowStripView(now: NowResponse): NowStripView {
  return {
    severity: now.quiet ? "quiet" : "warning",
    headline: now.headline,
  };
}
