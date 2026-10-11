import { test, expect } from "@playwright/test";

// Seed: run 1 (done, 1 trade with legs), failed RELIANCE alert (timeout), health warning.
const ROUTES = [
  "/today", "/positions", "/alerts", "/backtests", "/backtests/1",
  "/sweeps", "/journal", "/analytics", "/health", "/settings",
];
const SHOTS = "test-results/api-screenshots";

function trackErrors(page: import("@playwright/test").Page) {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test.describe("real API", () => {
  for (const route of ROUTES) {
    test(`loads ${route} without console errors`, async ({ page }) => {
      const errors = trackErrors(page);
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(500);
      const slug = route.replace(/\//g, "_").replace(/^_/, "") || "root";
      await page.screenshot({ path: `${SHOTS}/${slug}.png`, fullPage: true });
      expect(errors, `console errors on ${route}: ${errors.join("; ")}`).toEqual([]);
    });
  }

  test("SPA is served by the API and /api/health is JSON", async ({ request }) => {
    const html = await request.get("/backtests/1");
    expect(html.headers()["content-type"]).toContain("text/html");
    const health = await request.get("/api/health");
    expect(health.ok()).toBe(true);
    expect(await health.json()).toBeTruthy();
  });

  test("Today shows the failed-alert Now strip", async ({ page }) => {
    await page.goto("/today");
    await expect(page.getByText(/RELIANCE.*failed to send.*timeout/i).first()).toBeVisible();
  });

  test("backtest page shows the seeded run's trade count and trade", async ({ page }) => {
    const errors = trackErrors(page);
    await page.goto("/backtests/1");
    await expect(page.getByText(/fewer than 100 trades \(1\)/)).toBeVisible();
    await page.getByRole("tab", { name: "Trades" }).click();
    await expect(page.getByRole("row", { name: /RELIANCE/ }).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/backtests_1_trades.png`, fullPage: true });
    expect(errors).toEqual([]);
  });

  test("replay renders real candles and legs", async ({ page, request }) => {
    const errors = trackErrors(page);
    const replay = await (await request.get("/api/backtests/1/trades/1/replay")).json();
    expect(replay.candles.length).toBe(75);
    expect(replay.markers.map((m: { kind: string }) => m.kind)).toEqual(
      ["entry", "partial_exit", "trail_update", "stop_hit"]);

    await page.goto("/backtests/1");
    await page.getByRole("tab", { name: "Replay" }).click();
    await page.waitForTimeout(600);
    for (let i = 0; i < 20; i++) await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(300);
    await expect(page.locator("canvas").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/backtests_1_replay.png`, fullPage: true });
    expect(errors).toEqual([]);
  });
});
