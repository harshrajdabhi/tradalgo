# Dashboard v2 — design plan (B2)

## 1. Subject, audience, jobs

**Subject.** tradalgo is an alerts-only NSE intraday assistant. It never places orders — it watches the market, scores setups, and pushes Telegram alerts the user acts on by hand from a broker terminal. The dashboard is the desk instrument next to that terminal: a place to see what needs a decision, watch open risk, and judge whether the strategy itself is still working.

**Audience.** One person: the trader/operator, on a laptop, market hours plus evening review. No multi-user chrome, no onboarding, no marketing surface.

**Primary jobs, in order:**
1. What needs my action right now (failed alert, an entry awaiting my reply, an open trade with no exit yet, kill switch).
2. How are today's open trades doing (unrealised R, levels, time in trade).
3. Is the strategy working — backtests (with live analysis while running), sweeps (train vs. test), live-vs-backtest drift.
4. Health and settings — token expiry, kill switch, config edits.

Everything in the IA below is ordered to match this list, not alphabetically or by "how the code is organized."

## 2. Information architecture

Left rail, icon + label, fixed width, collapsible to icons only (desk use next to a broker window is tight on horizontal space):

```
Today · Positions · Alerts · Backtests · Sweeps · Journal · Analytics · Health · Settings
```

- **Today** — the Now strip + shortlist + signals feed. Landing page.
- **Positions** — open trades with live levels.
- **Alerts** — renamed from "Telegram": alert history, resend, delivery status.
- **Backtests** — list → run detail (queue form lives here too, not a separate page).
- **Sweeps** — grid results, train vs. test.
- **Journal** — closed trades, CSV export.
- **Analytics** — aggregate performance, by-strategy/by-regime.
- **Health** — token expiry, worker/API status.
- **Settings** — validated config form, kill switch.

Keyboard shortcuts (global, desk-terminal habit — number keys switch pages without touching the mouse):
- `1`–`9` jump to rail items in order above.
- `g` then a letter is not used (avoids two-key chords conflicting with browser find); plain digits are enough for nine pages.
- `/` focuses the page's primary filter/search field where one exists.
- `Esc` clears focus / closes an open panel.
- Replay-specific bindings are listed in §4b.

Layout shell: a 56px icon rail (96px expanded with labels) on the left, content area with a max content width of 1440px centered on wider monitors so line lengths and chart aspect ratios stay readable, no marketing-style full-bleed hero. Dense, not cramped: 8px base spacing grid (see tokens), one page-level heading per view stated as what it shows, not a label above a label.

## 3. Token system

### 3.1 Color

Carried forward unchanged from the accepted Streamlit review (do not re-litigate what already passed critique):

| Token | Hex | Role |
|---|---|---|
| `paper` | `#EEF1F4` | Page background — cool blue-grey, not warm cream |
| `panel` | `#E4E8EC` | Secondary surface (rail, cards) |
| `ink` | `#16233D` | Primary text |
| `ink-muted` | `#55617A` | Secondary text, axis labels |
| `line` | `#D8D9D3` | Hairlines, dividers, grid |
| `gain` | `#2F6D4F` | Positive P&L/R numbers only |
| `loss` | `#8C3B34` | Negative P&L/R numbers only |
| `action` | `#B4750F` | "Needs your action" states only — never decorative |

Measured contrast (WCAG relative-luminance formula, computed, not eyeballed):

| Pair | Ratio | Passes |
|---|---|---|
| ink / paper | 13.80:1 | AAA body text |
| ink / panel | 12.71:1 | AAA body text |
| ink-muted / paper | 5.49:1 | AA body text (≥4.5:1) |
| gain / paper | 5.41:1 | AA body text |
| loss / paper | 6.64:1 | AA body text |
| action / paper | 3.37:1 | AA UI/graphical only (≥3:1) — never run action-colored body copy; it is a stroke/icon/badge color |
| line / paper | 1.25:1 | decorative only, not text |

New, added for v2 surfaces (Backtests live view, replay, chart lines). Named, not ad hoc:

| Token | Hex | Role | Contrast on paper |
|---|---|---|---|
| `vwap` | `#5B7C99` | VWAP line on candle charts | 3.87:1 (line/graphic use, ≥3:1) |
| `accent-cool` | `#2E5C8A` | Neutral chart accent (equity curve line, non-P&L series) — distinct from ink so it doesn't read as body text color reused | 6.02:1 |

Chart series reuse the semantic set rather than invent a rainbow:
- Candle up → `gain`, candle down → `loss` (same meaning as everywhere else: green/red is reserved for direction and P&L, never used for anything neutral).
- VWAP → `vwap` (a distinct blue-grey so it never gets mistaken for entry/stop/target, which are structural, not price-derived).
- Entry line → `ink` (dashed). Stop line → `loss` (solid — it is where you lose). Partial/target line → `gain` (solid — it is where you take money). Runner/trail stop → `loss` at reduced opacity (0.55) to distinguish "current protective stop, already trailed" from the original stop.
- Equity curve → `accent-cool`. Drawdown shading → `loss` at 12% fill opacity under the curve, never a solid block (keeps the loss color meaningful — a wash, not a warning).
- R-multiple histogram bars → `gain` for bars ≥0R, `loss` for bars <0R (same rule as everywhere: color follows sign, not category).
- `action` (amber) appears in charts exactly once: a vertical marker on the replay timeline for "alert sent" / "awaiting your reply" — because that is the one moment on a chart that is actually asking for something from the user, consistent with the strip rule.

**Dark theme** (evening review only, opt-in, not the default — most sessions are market-hours daylight use next to a lit broker terminal). The brief flags "near-black + neon" as the generic tell; this stays in the same cool, low-saturation family as the light theme rather than jumping to charcoal-and-cyan:

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `paper-dark` | `#1B2431` | Page background — a dim version of the same navy family, not `#0B0B0B` | — |
| `panel-dark` | `#232E3D` | Secondary surface | ink-dark/panel-dark 11.3:1 |
| `ink-dark` | `#E7E9EE` | Primary text | 12.87:1 on paper-dark |
| `ink-muted-dark` | `#9AA5B8` | Secondary text | 6.29:1 on paper-dark |
| `line-dark` | `#334052` | Hairlines | decorative |
| `gain-dark` | `#6FBE96` | Positive P&L/R | 7.06:1 |
| `loss-dark` | `#D98E82` | Negative P&L/R | 6.06:1 |
| `action-dark` | `#E3A64C` | Needs-action | 7.31:1 |

Same desaturated, cool-neutral palette lifted in lightness and dropped in chroma for the dark surface — not a hue swap, not a saturation boost. No neon; amber stays amber, just lighter, so "needs action" is instantly recognizable switching between themes.

### 3.2 Type

Keep **Public Sans** (Google Fonts, OFL, real numeral tabular-figure support via `font-variant-numeric: tabular-nums` — this already survived review and reads as a deliberate "government-form clarity" choice for a numbers-dense desk tool, not a generic Inter/Roboto default). One family, two weights doing the work of two roles: 600 for headings and KPI numbers, 400 for body and table text. No second typeface — a data desk doesn't need a display face, it needs everything to line up.

Type scale (1.25 ratio, base 15px — slightly denser than a marketing page because rows of data are the content):

| Role | Size / line-height | Weight |
|---|---|---|
| Page heading | 20px / 28px | 600 |
| Section heading | 16px / 24px | 600 |
| Body / table cell | 15px / 22px | 400 |
| Small / metadata | 13px / 18px | 400 |
| KPI number (Now strip, run summary) | 28px / 32px | 600, tabular-nums |
| Micro label (chart axis) | 11px / 14px | 400 |

No ALL CAPS labels anywhere (flagged default, see §6). Section headings are sentence case, stated as what the section contains ("Trades so far", not "TRADES").

### 3.3 Layout, spacing, radius, elevation

- 8px base spacing unit; component padding in multiples of 8 (8/16/24/32).
- Radius: 4px on cards and inputs, 2px on badges/pills. One radius scale, applied by role, not "the same rounded-card everywhere" — dense data tables use square corners (0px) because a table is a grid, not a card.
- Elevation: no drop shadows. Separation is done with the `line` hairline and background-tone steps (`paper` → `panel` → `#FFFFFF` for the topmost surfaces like the Now strip and modal), matching what already worked in the Streamlit review. This directly avoids the "same soft grey box-shadow under every card" default.
- Grid: 12-column content grid, gutters 24px, page margin 32px (16px under 900px width).

### 3.5 Component foundation: MUI v6, themed away from stock Material

Binding direction from the user overrides the earlier "no UI kit" line: build on **MUI v6** (`@mui/material`, MIT) with a fully custom `createTheme()` driven entirely by the token system above — not the stock Material look. Concretely:

- `palette`: `primary.main = ink`, no Material purple/blue anywhere; `success.main = gain`, `error.main = loss`, `warning.main = action` (this is what lets `MuiChip`/`MuiAlert` severities map onto the existing semantic rule instead of inventing a second color language). `background.default = paper`, `background.paper = "#FFFFFF"` (the one truly white surface, reserved the same way it was in the Streamlit version — Now strip, modals, the topmost card).
- `typography`: `fontFamily` = Public Sans everywhere (`h1`…`overline` all mapped, not left on Roboto — MUI defaults to Roboto and that default is exactly the generic-SaaS tell to avoid). `fontFamily` for `.MuiDataGrid-cell` and any numeric `Typography` variant additionally sets `fontVariantNumeric: "tabular-nums"`. Scale matches §3.2 (page heading → `h5` at 20px/600, section heading → `h6` at 16px/600, body → `body1` at 15px/400, small → `caption` at 13px).
- `shape.borderRadius`: 4 (cards/inputs). Table-shaped surfaces (`DataGrid`) override to 0 locally — MUI's single global radius is exactly the "one border-radius on everything" default called out in §6, so it is deliberately overridden per-component rather than left global.
- `components` overrides, each with a reason:
  - `MuiPaper` / `MuiCard`: `elevation` forced to a 1px `line`-colored border, `boxShadow: "none"` at every elevation level. MUI's default drop-shadow-per-elevation is the generic SaaS-card tell; separation comes from the tone-step + hairline system in §3.3, not shadow.
  - `MuiButton`: `disableElevation: true`, sentence-case labels (MUI defaults buttons to uppercase — disabled globally via `textTransform: "none"`, which also removes the ALL-CAPS default flagged in §6).
  - `MuiChip`: used only for the three semantic states (gain/loss/action) and neutral tags (strategy name, regime) — never as decorative badges. Neutral chips use `variant="outlined"` in `ink-muted`/`line`, not filled, so only the three semantic chips carry a filled color.
  - `MuiAlert`: the **Now strip** is a custom `MuiAlert` variant (`severity="warning"` when something needs action, a custom `severity="quiet"` — added via `variants` — mapped to `ink-muted`/`line` when nothing does), left-border 4px in the severity color, white background, replacing MUI's default pastel-tinted alert fill (which reads as generic Material) with the white-surface/colored-border look that already passed review.
  - `MuiDataGrid` (from `@mui/x-data-grid`): density `"compact"` by default (a desk tool wants rows, not Material's default comfortable spacing), header background `panel`, row divider `line`, no zebra striping (striping fights the hairline-only separation principle), sort/filter icons sized down to match the 15px body type.
  - `MuiTabs`/`MuiTab`: underline indicator in `ink`, no filled/pill tab default.
  - `MuiSlider` (replay scrubber): track in `line`, active track in `ink`, thumb a plain circle in `ink` with no drop shadow — avoids MUI's default blue slider entirely.
- Dark theme: a second `createTheme()` sharing the same shape/typography/component overrides, palette swapped to the `-dark` token set in §3.1 (`mode: "dark"` plus explicit palette values — MUI's own dark-mode defaults are not used, to avoid drifting toward its default near-black surfaces).

This keeps the "no generic SaaS look" commitment from the original brief intact while satisfying the new, more specific instruction to build on MUI and open-source libraries: the constraint moved from "hand-built components" to "MUI components with every default that reads as generic Material explicitly overridden," which is the same design intent expressed through a different (and now mandated) implementation path.

### 3.4 The one bold element

Per page, exactly one component is allowed to be visually loud: the **Now strip** on Today (unchanged — amber left-border, white surface against the cool paper, larger type, top of page) is the single bold element for the whole app. Every other page inherits its restraint: the Backtest run detail's "gate verdict" badge is the equivalent bold element on that page, and the replay's amber alert-marker is the equivalent on the replay view. No page has two loud things.

## 4. Page layouts

### 4a. Today

```
┌─────────────────────────────────────────────────────────────┐
│ Today                                          [kill switch] │
│ ┌───────────────────────────────────────────────────────┐   │
│ │▐ RELIANCE alert failed to send (timeout). Resend it    │   │  ← Now strip
│ │▐ from Alerts.                                          │   │    (the one bold element)
│ └───────────────────────────────────────────────────────┘   │
│                                                               │
│ Shortlist                              Signals               │
│ ┌─────────────────────────┐   ┌───────────────────────────┐ │
│ │ Symbol  Score  Regime    │   │ 09:41  RELIANCE  entry ▲  │ │
│ │ RELIANCE  78   trending  │   │ 09:38  TCS       skip     │ │
│ │ TCS       61   range     │   │ 09:22  INFY      entry ▲  │ │
│ │ …                        │   │ …                          │ │
│ └─────────────────────────┘   └───────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```
Shortlist rows show factor scores as a small horizontal bar next to the number (not a sparkline — the score is one number, one bar, no false precision). Signal feed is reverse-chronological, entries flagged with a small triangle glyph (▲ taken / — skipped), not a colored pill (color stays reserved for gain/loss/action).

Components: Now strip = custom `MuiAlert` variant (§3.5). Shortlist = `@mui/x-data-grid` `DataGrid`, compact density, a custom `renderCell` for the score bar (an inline `Box` width driven by score, not a chart). Signal feed = a plain `List`/`ListItem` stack (MUI), not a `DataGrid` — it's a log, not a sortable table.

### 4b. Positions

```
┌─────────────────────────────────────────────────────────────┐
│ Positions                                                    │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ RELIANCE  qty 40  entry 2,845.10  stop 2,822  +0.6R    │   │
│ │ [ mini candle · VWAP · entry/stop lines ]               │   │
│ ├───────────────────────────────────────────────────────┤   │
│ │ TCS       qty 25  entry 3,910.00  stop 3,940  −0.2R    │   │
│ │ [ mini candle · VWAP · entry/stop lines ]               │   │
│ └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```
Each open position is a row with an inline mini price chart (candles + VWAP + entry/stop), not a separate drill-down — the point of the page is "how is it doing right now" at a glance. R value colored gain/loss per rule; everything else ink/ink-muted.

Components: outer list = MUI `Card`/`Paper` per position (bordered, not shadowed, per §3.5). R value = `Typography` with `color: gain|loss`. Mini chart = TradingView `lightweight-charts`, small fixed-height instance per row, same series config as the replay chart but no playback controls.

### 4c. Backtests — list and run detail

List page: a plain table (symbol-density, no cards) of past runs — id, date range, strategy set, status, net R, gate verdict badge — plus the queue form as a compact inline panel above the table, not a modal (queuing a run is a primary action here, not an edge case).

**Run detail — LIVE state** (polling `/api/backtests/{id}/live` at 3s while `status=running`):

```
┌─────────────────────────────────────────────────────────────┐
│ Backtest #142  2026-03-01 → 2026-09-11        ● running 62%  │
│ ┌───────────────┬───────────────┬───────────────┬─────────┐ │
│ │ Trades so far │ Expectancy R  │ Win rate       │ Net R   │ │
│ │     37        │    +0.18      │    54%         │  +6.2   │ │
│ └───────────────┴───────────────┴───────────────┴─────────┘ │
│ Equity curve (grows as trades complete)                      │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ ╱╲___╱‾╲__╱‾‾╲                                          │   │
│ └───────────────────────────────────────────────────────┘   │
│ R-multiple histogram        By strategy (updating)           │
│ ┌───────────────────┐       ┌───────────────────────────┐   │
│ │ ▁▃█▅▂ ▁▂          │       │ orb        14  +0.22       │   │
│ └───────────────────┘       │ vwap-rev   11  −0.05       │   │
│                              └───────────────────────────┘   │
│ Latest trades                                                │
│ 09:41 RELIANCE +1.2R · 09:22 TCS −1.0R · 09:05 INFY +0.4R    │
└─────────────────────────────────────────────────────────────┘
```
The progress ring/bar and "● running" dot are the only continuously-animating element on this page (see §5 — a live run is the one place ambient motion is earned). Equity curve redraws by appending the newest point, not re-animating the whole line, so it reads as "growing," not "re-rendering."

The run detail is a single page with `MuiTabs`: **Live** (default while running) · **Trades** · **Replay** · **Diagnostics** (default once finished — the tab that opens by default flips with `status`, so the user always lands on the currently-relevant view). Components: KPI tiles = `Grid` of `Paper` cards with a `Typography` `h5` number + `caption` label. Progress = `LinearProgress` (determinate, `percent` from the payload) plus the pulsing status dot from §5. Equity curve, R histogram, by-strategy bars = `@mui/x-charts` (`LineChart`, `BarChart`) themed to the token palette (§3.1 dataviz mapping), not its default categorical palette. Latest trades = compact `List`. Trades tab = `DataGrid` (sortable, filterable, exportable — CSV export reused on Journal too) with a row action opening Replay for that trade.

**Run detail — FINISHED state** replaces the live strip with a **gate verdict badge** (this page's one bold element): "Gate passed" in a gain-tinted badge, or "Gate not passed — 62 trades (need 100)" in a loss-tinted badge with the actual reason inline, not a generic failure. Below it, diagnostics as scannable visuals, not raw tables:
- **By hour** → a small horizontal bar strip, one bar per trading hour, height = trade count, color = that hour's average R sign.
- **By exit reason** → a horizontal stacked bar (stop / target / trail / eod), each segment labeled with its share.
- **MFE buckets** → a histogram, same visual language as the R-multiple histogram above.
- **Fill rate** → a single large percentage with a thin ring, next to "missed entries" count as plain text underneath (not a second chart for one number).
- **Rejections** → a compact list, grouped by reason, count only — expandable to the raw rows on click for the rare time the raw list is needed.

Components (Diagnostics tab): gate verdict = a `Chip` (`color="success"|"error"`, filled — the one filled chip usage, deliberately, since this is the page's bold element per §3.4) with the reason as adjoining `Typography`. By-hour and MFE-bucket visuals = `@mui/x-charts` `BarChart`. By-exit-reason = `@mui/x-charts` stacked `BarChart` (horizontal). Fill rate ring = MUI `CircularProgress` (determinate) with the percentage as centered `Typography`, not a `@mui/x-charts` gauge (community edition has no gauge component — see Dependencies). Rejections list = `List` with `Accordion` per reason group for the expand-to-raw-rows behavior.

### 4b (deep) — Trade replay

Opened from a trade row in the run detail's trade list or the Journal. Full-width, two-pane:

```
┌───────────────────────────────────────────┬─────────────────┐
│ RELIANCE · 2026-08-14           ◀ prev next▶ │ At playhead      │
│ ┌─────────────────────────────────────────┐ │ Time  10:14:00   │
│ │        candles, VWAP, entry/stop/        │ │ Open qty   40    │
│ │        target/trail lines, event         │ │ Unreal. R  +0.4  │
│ │        markers (● entry ● partial        │ │ Stop    2,822    │
│ │        ● trail ● stop ● exit)            │ │ Next event       │
│ │                                           │ │  partial @ 10:15 │
│ └─────────────────────────────────────────┘ │                  │
│ ├────────────────────────────────────────┤  │                  │
│ ⏮ ⏵ ⏭   ────●──────────────────  1x ▾    │  └─────────────────┘
│ 09:15                              15:30     │
└───────────────────────────────────────────┴─────────────────┘
```
- Chart: TradingView `lightweight-charts`, candles for the session, VWAP overlay, horizontal reference lines for entry/stop/partial/runner-target, markers at each event on the bar they occurred. Bars beyond the playhead are hidden (not just dimmed) — the point is watching price arrive at each level in sequence, not seeing the whole answer up front.
- Playback: play/pause, step ±1 bar, speed selector (1x / 2x / 4x), and a scrub bar synced to session time. Scrubbing reveals bars up to that point exactly as playing would.
- Side panel updates live with the playhead: open quantity, unrealised R, current (possibly trailed) stop, and the next scheduled event — this is what makes it a *replay* rather than a chart with lines on it.
- Prev/Next trade navigation moves to the adjacent trade in the same run without leaving the replay view.

Keyboard shortcuts on this view only: `space` play/pause, `←`/`→` step one bar, `↑`/`↓` change speed, `[`/`]` prev/next trade, `Esc` returns to the run detail. This is the one page where continuous motion (auto-advancing playback) is not just allowed but the point — explicitly the exception called out in §5.

Components: chart = TradingView `lightweight-charts` candlestick series + line series (VWAP, entry/stop/target/trail) + markers API for events — MUI plays no role inside the chart canvas itself. Controls = `IconButton` (play/pause/step, `@mui/icons-material` `PlayArrow`/`Pause`/`SkipPrevious`/`SkipNext`), `MuiSlider` for the scrub bar (themed per §3.5), a `Select` for speed. Event timeline under the scrubber (entry/partial/trail/stop/exit ticks) = a custom thin `Stepper`-like strip built from MUI `Step`/`StepLabel` laid horizontally with `orientation` overridden, reusing its connector-line visual for "sequence of events" (a genuine sequence, consistent with §6's numbered-marker carve-out) rather than a from-scratch component. Side panel = `Card` with a label/value `Grid`. Prev/next = `IconButton`s in the header.

### 4d. Sweeps

```
┌─────────────────────────────────────────────────────────────┐
│ Sweeps                                                        │
│ Combo            Train R    Test R    Δ         Overfit?      │
│ orb·tight-stop    +8.2      +1.1     −7.1        ⚠ flagged    │
│ orb·wide-stop     +5.4      +4.9     −0.5        ok            │
│ vwap-rev·std      +6.0      +5.8     −0.2        ok            │
└─────────────────────────────────────────────────────────────┘
```
Train and test R sit in adjacent columns (not separate tables) specifically so a large gap is visible without doing mental subtraction; the Δ column makes it explicit and a row crossing a fixed overfit threshold gets the ⚠ glyph plus `action`-colored left border on that row only — the same "needs your action" amber used everywhere else, because a flagged combo is exactly that: something the user must not blindly deploy. No color used for "good" (ok is just ink-muted text, not a green pill) — gain/loss stays reserved for R-numbers, not row status.

Components: `DataGrid` with a `getRowClassName` applying the amber left-border style conditionally, `renderCell` on Train R/Test R for gain/loss `Typography` coloring, and a small `@mui/x-charts` `BarChart` (train vs. test paired bars) above the table as an at-a-glance summary before the detail rows.

## 5. Interaction and motion

- Default: no entrance animation on page load, no hover-lift on cards, no scroll-triggered reveals. Pages render complete and static — this is a desk tool checked mid-trade, not a landing page.
- Purposeful exceptions:
  1. Backtest run detail while `status=running`: the status dot pulses gently (opacity 1↔0.5, 1.6s ease) and the equity curve appends new points — both are *information* (a run is progressing), not decoration.
  2. Replay playback: the explicit, user-controlled exception described above.
  3. State transitions that show what changed: resending an alert flips its row from "failed" to "sent" with a 150ms color crossfade, not a re-render flash.
- `prefers-reduced-motion: reduce` disables the status-dot pulse and the alert crossfade; replay playback itself still runs (it's the user pressing play, not ambient motion) but its default frame-advance easing drops to a linear step.
- Loading states: replace the KPI/table area with a low-contrast placeholder shaped like the real content (same row heights) and the copy "Loading trades…" — never a spinner alone with no label.
- Empty states, actual copy (sentence case, plain verbs, per the writing guidance):
  - Today, nothing to do: "No action needed. Next check at 09:56."
  - Positions, none open: "No open positions right now."
  - Backtests, none run yet: "No backtests yet. Queue one above to see results here."
  - Sweeps, none run: "No sweeps yet. Run one from the command line, then results appear here."
  - Journal date range with no trades: "No closed trades in this range."
- Error states, actual copy:
  - Backtest queue rejected: "Can't queue this backtest: end date is before start date." (states what's wrong, not "validation error")
  - Alert resend fails: "Resend failed: Telegram timed out. Try again in a moment."
  - Candle data missing for replay: "No price data for this session. The trade may be outside the stored candle range."
- Accessibility floor: every interactive element has a visible focus ring (2px solid `ink`, 2px offset — carried over from the Streamlit CSS rule); replay is fully keyboard-operable (§4b shortcuts) with no mouse-only control; all chart lines have a non-color-dependent cue too (dash pattern for entry vs. solid for stop/target, marker shape per event type) so the page still reads under color-vision deficiency; tab order follows visual order on every page.

## 6. Review against the skill's generated-design defaults

| Default flagged by the skill | Present in this plan? | Disposition |
|---|---|---|
| Warm cream background (~`#F4F1EA`) + terracotta accent | No | Already rejected in the prior Streamlit review; kept `paper` as a cool blue-grey (`#EEF1F4`), no terracotta anywhere. Confirmed still avoided in v2. |
| Near-black background + neon accent | No | The dark theme (§3.1) is a dimmed version of the same navy family (`#1B2431`), not `#0B0B0B`, and amber/green/red stay desaturated — no neon. Checked explicitly while writing §3.1 because "evening review dark mode" is exactly where this default tends to sneak in. |
| Broadsheet layout, hairline rules, zero radius, dense newspaper columns | Partially present, deliberately | Hairlines are used (`line` token) because a trading desk table benefits from real dividers, and dense tables do use 0px radius — but this is a choice tied to the subject (a desk instrument reads correctly with grid-like density), not a broadsheet aesthetic wholesale: cards/inputs still get 4px radius, there's no serif display type, no multi-column prose. |
| SaaS-card kit: identical rounded cards, one border-radius everywhere, uniform grey drop-shadow, gradient washes | No | No drop shadows anywhere (§3.3) — separation via hairline + tone step instead. Radius varies by role (cards 4px, tables 0px, badges 2px) rather than one blanket value. No gradients. |
| Stock Material look (purple/blue primary, elevated cards, Roboto, uppercase buttons) — the risk of the newer "build on MUI" instruction | Addressed directly in §3.5 | `primary` is `ink`, not Material's default indigo/blue; `boxShadow` zeroed at every `Paper`/`Card` elevation in favor of a hairline border; `fontFamily` remapped to Public Sans on every typography variant, not left on Roboto; `MuiButton` uppercase transform disabled. Confirmed the token system, not MUI's defaults, drives every visible surface. |
| Tracked-out ALL-CAPS eyebrow labels | No | Section headings are sentence case, stated as content ("Trades so far"), not eyebrow labels above headings. |
| Meta strings joined with middot ('A · B · C') | Used once, reconsidered, kept narrowly | The Today "latest trades" inline strip in §4a joins entries with `·` for compact scanning of a genuinely list-like row of independent same-shaped facts (time · symbol · R) — this is the one place it's actually functional density, not chrome. Not used anywhere else (page headers, nav, cards all avoid it). |
| Labels as 'WORD — fragment' with spaced em dash | No | Not used anywhere in copy. |
| Tinted near-black (`#0B0B0B`/`#111`) standing in for true black | No | `ink` is `#16233D`, a real navy, in both themes; nothing uses a near-black. |
| Monospace face for data labels | No | Tabular-nums on Public Sans handles numeral alignment (already proven in the Streamlit review); no monospace face introduced. |
| Appended '→' on links/buttons | No | Button/link copy states the action verb only ("Resend", "Queue backtest"), no arrow glyphs. |
| Single-word/phrase accent inside a headline (bold/italic/color on one word) | No | Page headings are plain; the gate verdict and Now strip get their emphasis from being a distinct component (badge/strip), not from styling one word within a sentence. |
| Numbered markers (01/02/03) for non-sequential content | No | The IA list and page sections are never numbered; the only ordering markers used are the actual step bar in replay (a true sequence) and rank numbers in the shortlist score table (a true ranking) — both are genuine sequences per the skill's own carve-out. |
| Default hero: big number + small label + gradient accent | Reconsidered for Today | Today's "hero" is the Now strip — a full-width sentence, not a big-number tile, specifically because the primary job is "what needs my action," which is a sentence with content, not a metric. KPI number tiles are used only on the backtest run detail where the content genuinely is a set of metrics (§4c) — no gradient anywhere. |

Changes made during this review pass: none of the above required reversing an existing decision — the one item worth flagging was the middot usage in §4a, which I checked against the "meta strings joined with middots" default and narrowed to a single justified use (a compact log-line of independent equal-weight facts) rather than removing it outright, since removing it there would force three separate columns for what is genuinely one glanceable line.

## 7. Build notes

Component inventory and data source, for the B3 implementer:

| Component | Page(s) | Endpoint(s) | Poll |
|---|---|---|---|
| `NowStrip` | Today | `/api/now` | 15s |
| `Shortlist` | Today | `/api/shortlist?date` | 15s |
| `SignalFeed` | Today | `/api/signals?date` | 15s |
| `PositionRow` (+ mini candle) | Positions | `/api/positions`, `/api/candles/{symbol}?date` | 15s |
| `AlertTable`, resend action | Alerts | `/api/alerts?status&date`, `POST /api/alerts/{id}/resend` | 15s |
| `KillSwitchToggle` | Today, Settings | `POST /api/kill-switch` | on action |
| `BacktestQueueForm` | Backtests (list) | `POST /api/backtests` | — |
| `BacktestList` | Backtests (list) | `GET /api/backtests` | 15s |
| `LiveRunPanel` (KPIs, growing equity curve, R histogram, by-strategy table, latest trades) | Backtests (run detail, running) | `GET /api/backtests/{id}/live` | **3s while `status=running`**, otherwise stop polling |
| `GateVerdictBadge` | Backtests (run detail, finished) | `GET /api/backtests/{id}` | on load |
| `DiagnosticsPanel` (by hour, by exit reason, MFE buckets, fill rate, rejections) | Backtests (run detail, finished) | `GET /api/backtests/{id}` | on load |
| `TradeList` | Backtests (run detail) | `GET /api/backtests/{id}/trades` | on load / after live update |
| `ReplayChart` (lightweight-charts candles + VWAP + level lines + markers) | Trade replay | `GET /api/candles/{symbol}?date`, `GET /api/backtests/{id}/trades/{trade_id}/replay` | on open |
| `ReplayControls` (play/pause/step/speed/scrub) | Trade replay | client-side only, drives which bars/markers render | — |
| `ReplaySidePanel` | Trade replay | derived from `replay` payload at current playhead index | — |
| `SweepTable` (train/test/Δ/overfit flag) | Sweeps | `/api/sweeps`, `/api/sweeps/{id}` | 15s |
| `JournalTable` + CSV export | Journal | `/api/journal?from&to&strategy&symbol` | on filter change |
| `AnalyticsPanel` | Analytics | `/api/analytics` | 15s |
| `HealthPanel` (token expiry, worker/API status) | Health | `/api/health` | 15s |
| `SettingsForm` (validated) | Settings | `GET/PUT /api/settings` | on load / on save |

Polling rule, app-wide: 15s default on every list/state endpoint; the moment any backtest or sweep has `status=running`, the owning view switches to 3s until it finishes, then reverts to 15s. TanStack Query's `refetchInterval` should be a function of the current query data (`data.status === "running" ? 3000 : 15000`), not a static per-route constant, so a run finishing mid-session drops back to 15s without a page reload.

Chart library: TradingView `lightweight-charts` for every candle view (Positions mini-charts, replay). Equity curve, R-multiple histogram, by-strategy/by-hour bars, and MFE buckets use `@mui/x-charts` (community, MIT), themed to the token palette rather than its default categorical colors — this supersedes the earlier "hand-built SVG" note now that the brief calls for MUI/open-source libraries throughout.

## 8. Dependencies (MIT/Apache only)

| Package | Version range | License | Use |
|---|---|---|---|
| `@mui/material` | ^6 | MIT | Component foundation, themed per §3.5 |
| `@mui/icons-material` | ^6 | MIT | Iconography (rail, playback controls, chips) |
| `@mui/x-data-grid` | ^7 (community) | MIT | Every table: Shortlist, Trades, Journal, Sweeps, Alerts |
| `@mui/x-charts` | ^7 (community) | MIT | Equity curve, R histogram, by-hour/by-exit/MFE bars, sweep train-vs-test bars |
| `@mui/x-date-pickers` | ^7 (community) | MIT | Journal/Alerts date-range filters, with `dayjs` as the adapter |
| `dayjs` | ^1 | MIT | Date handling for the above |
| `lightweight-charts` | ^4 | Apache-2.0 | Candlestick + VWAP + price lines + markers (Positions mini-charts, Replay) |
| `@tanstack/react-query` | ^5 | MIT | Polling/caching for every endpoint in §7 |
| `react-router-dom` | ^6 | MIT | Routing across the nine pages in §2 |

**Community-edition boundary (no Pro/Premium, no commercial license):** `@mui/x-data-grid` community supports sorting, filtering, column show/hide, and CSV export (`GridToolbar`'s built-in export) — everything the Journal/Trades/Sweeps grids need — but not row grouping/pivoting or the pro-only Excel export; not needed here so no Pro tier is required. `@mui/x-charts` community covers line/bar/scatter (equity curve, histograms, MFE scatter) but has **no gauge/heatmap component in community** — the fill-rate "ring" in §4c deliberately uses plain MUI `CircularProgress` instead of an `@mui/x-charts` gauge for exactly this reason, and no heatmap visualization is proposed anywhere in this plan. If a future page wants row grouping or a gauge, that's the trigger to revisit an MUI X Pro license — not assumed here.
