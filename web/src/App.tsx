import { useEffect, useRef } from "react";
import { Routes, Route, useNavigate, useLocation, NavLink } from "react-router-dom";
import Box from "@mui/material/Box";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import TodayIcon from "@mui/icons-material/Today";
import ShowChartIcon from "@mui/icons-material/ShowChart";
import NotificationsIcon from "@mui/icons-material/Notifications";
import ScienceIcon from "@mui/icons-material/Science";
import TuneIcon from "@mui/icons-material/Tune";
import MenuBookIcon from "@mui/icons-material/MenuBook";
import BarChartIcon from "@mui/icons-material/BarChart";
import FavoriteIcon from "@mui/icons-material/MonitorHeart";
import SettingsIcon from "@mui/icons-material/Settings";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";

import TodayPage from "./pages/TodayPage";
import PositionsPage from "./pages/PositionsPage";
import AlertsPage from "./pages/AlertsPage";
import BacktestsPage from "./pages/BacktestsPage";
import BacktestDetailPage from "./pages/BacktestDetailPage";
import SweepsPage from "./pages/SweepsPage";
import SweepDetailPage from "./pages/SweepDetailPage";
import JournalPage from "./pages/JournalPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import HealthPage from "./pages/HealthPage";
import SettingsPage from "./pages/SettingsPage";

const NAV = [
  { path: "/today", label: "Today", icon: <TodayIcon fontSize="small" /> },
  { path: "/positions", label: "Positions", icon: <ShowChartIcon fontSize="small" /> },
  { path: "/alerts", label: "Alerts", icon: <NotificationsIcon fontSize="small" /> },
  { path: "/backtests", label: "Backtests", icon: <ScienceIcon fontSize="small" /> },
  { path: "/sweeps", label: "Sweeps", icon: <TuneIcon fontSize="small" /> },
  { path: "/journal", label: "Journal", icon: <MenuBookIcon fontSize="small" /> },
  { path: "/analytics", label: "Analytics", icon: <BarChartIcon fontSize="small" /> },
  { path: "/health", label: "Health", icon: <FavoriteIcon fontSize="small" /> },
  { path: "/settings", label: "Settings", icon: <SettingsIcon fontSize="small" /> },
];

interface AppProps {
  mode: "light" | "dark";
  onModeChange: (m: "light" | "dark") => void;
}

export default function App({ mode, onModeChange }: AppProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const railRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (typing) return;
      if (e.key === "Escape") {
        (document.activeElement as HTMLElement | null)?.blur();
        return;
      }
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= NAV.length) {
        navigate(NAV[n - 1].path);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Box
        ref={railRef}
        component="nav"
        aria-label="Primary"
        sx={{
          width: 96,
          flexShrink: 0,
          borderRight: "1px solid",
          borderColor: "divider",
          bgcolor: "background.paper",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          position: "sticky",
          top: 0,
          height: "100vh",
        }}
      >
        <List sx={{ pt: 2 }}>
          {NAV.map((item, i) => {
            const active = location.pathname.startsWith(item.path);
            return (
              <Tooltip key={item.path} title={`${item.label} (${i + 1})`} placement="right">
                <ListItemButton
                  component={NavLink}
                  to={item.path}
                  selected={active}
                  sx={{
                    flexDirection: "column",
                    py: 1,
                    borderLeft: "3px solid transparent",
                    borderColor: active ? "primary.main" : "transparent",
                    "&.Mui-selected": { bgcolor: "action.selected" },
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 0, justifyContent: "center", color: "inherit" }}>
                    {item.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={item.label}
                    primaryTypographyProps={{ variant: "caption", textAlign: "center" }}
                  />
                </ListItemButton>
              </Tooltip>
            );
          })}
        </List>
        <Box sx={{ p: 1, display: "flex", justifyContent: "center" }}>
          <Tooltip title={mode === "light" ? "Switch to dark theme" : "Switch to light theme"}>
            <IconButton
              onClick={() => onModeChange(mode === "light" ? "dark" : "light")}
              aria-label="Toggle theme"
            >
              {mode === "light" ? <DarkModeIcon fontSize="small" /> : <LightModeIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      <Box component="main" sx={{ flexGrow: 1, bgcolor: "background.default", minWidth: 0 }}>
        <Box sx={{ maxWidth: 1440, mx: "auto", px: { xs: 2, md: 4 }, py: 3 }}>
          <Routes>
            <Route path="/" element={<TodayPage />} />
            <Route path="/today" element={<TodayPage />} />
            <Route path="/positions" element={<PositionsPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/backtests" element={<BacktestsPage />} />
            <Route path="/backtests/:id" element={<BacktestDetailPage />} />
            <Route path="/sweeps" element={<SweepsPage />} />
            <Route path="/sweeps/:name" element={<SweepDetailPage />} />
            <Route path="/journal" element={<JournalPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/health" element={<HealthPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </Box>
      </Box>
    </Box>
  );
}
