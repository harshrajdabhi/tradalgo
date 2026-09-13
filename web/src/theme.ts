import { createTheme, type ThemeOptions } from "@mui/material/styles";
import type {} from "@mui/x-data-grid/themeAugmentation";

// Token system — see docs/superpowers/plans/2026-09-14-dashboard-v2-design.md §3
export const tokens = {
  light: {
    paper: "#EEF1F4",
    panel: "#E4E8EC",
    white: "#FFFFFF",
    ink: "#16233D",
    inkMuted: "#55617A",
    line: "#D8D9D3",
    gain: "#2F6D4F",
    loss: "#8C3B34",
    action: "#B4750F",
    vwap: "#5B7C99",
    accentCool: "#2E5C8A",
  },
  dark: {
    paper: "#1B2431",
    panel: "#232E3D",
    white: "#232E3D",
    ink: "#E7E9EE",
    inkMuted: "#9AA5B8",
    line: "#334052",
    gain: "#6FBE96",
    loss: "#D98E82",
    action: "#E3A64C",
    vwap: "#5B7C99",
    accentCool: "#6FA0D6",
  },
};

const fontFamily = '"Public Sans", "Helvetica Neue", Arial, sans-serif';

function buildTheme(mode: "light" | "dark"): ThemeOptions {
  const t = tokens[mode];
  return {
    palette: {
      mode,
      primary: { main: t.ink },
      success: { main: t.gain },
      error: { main: t.loss },
      warning: { main: t.action },
      background: { default: t.paper, paper: t.white },
      text: { primary: t.ink, secondary: t.inkMuted },
      divider: t.line,
    },
    shape: { borderRadius: 4 },
    typography: {
      fontFamily,
      h5: { fontSize: 20, lineHeight: "28px", fontWeight: 600 },
      h6: { fontSize: 16, lineHeight: "24px", fontWeight: 600 },
      body1: { fontSize: 15, lineHeight: "22px", fontWeight: 400 },
      caption: { fontSize: 13, lineHeight: "18px", fontWeight: 400 },
      button: { textTransform: "none", fontWeight: 600 },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: { backgroundColor: t.paper },
          "*:focus-visible": {
            outline: `2px solid ${t.ink}`,
            outlineOffset: "2px",
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
            boxShadow: "none",
            border: `1px solid ${t.line}`,
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: { boxShadow: "none", border: `1px solid ${t.line}` },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: { root: { textTransform: "none" } },
      },
      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 2 },
          outlined: { borderColor: t.line, color: t.inkMuted },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: { backgroundColor: t.ink },
        },
      },
      MuiSlider: {
        styleOverrides: {
          root: { color: t.ink },
          track: { backgroundColor: t.ink, border: "none" },
          rail: { backgroundColor: t.line, opacity: 1 },
          thumb: { boxShadow: "none", "&:hover": { boxShadow: "none" } },
        },
      },
      MuiAlert: {
        styleOverrides: {
          root: {
            backgroundColor: t.white,
            borderLeft: `4px solid currentColor`,
            borderRadius: 4,
          },
        },
      },
      MuiDataGrid: {
        defaultProps: { density: "compact" },
        styleOverrides: {
          root: {
            borderRadius: 0,
            border: `1px solid ${t.line}`,
            "& .MuiDataGrid-columnHeaders": { backgroundColor: t.panel },
            "& .MuiDataGrid-cell": {
              fontVariantNumeric: "tabular-nums",
              borderColor: t.line,
            },
            "& .MuiDataGrid-row:hover": { backgroundColor: "transparent" },
          },
        },
      },
      MuiLinearProgress: {
        styleOverrides: {
          root: { backgroundColor: t.line },
        },
      },
    },
  };
}

export const lightTheme = createTheme(buildTheme("light"));
export const darkTheme = createTheme(buildTheme("dark"));

export function tokensFor(mode: "light" | "dark") {
  return tokens[mode];
}
