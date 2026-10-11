import { test, expect } from "@playwright/test";

const ROUTES = [
  "/today",
  "/positions",
  "/alerts",
  "/backtests",
  "/backtests/141",
  "/sweeps",
  "/sweeps/orb-stop-sweep",
  "/journal",
  "/analytics",
  "/health",
  "/settings",
];

test.describe("smoke", () => {
  for (const route of ROUTES) {
    test(`loads ${route} without console errors`, async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") errors.push(msg.text());
      });
      page.on("pageerror", (err) => errors.push(err.message));

      await page.goto(route);
      await page.waitForTimeout(500);

      const slug = route.replace(/\//g, "_").replace(/^_/, "") || "root";
      await page.screenshot({
        path: `test-results/screenshots/${slug}.png`,
        fullPage: true,
      });

      expect(errors, `console errors on ${route}: ${errors.join("; ")}`).toEqual([]);
    });
  }

  test("replay tab responds to keyboard controls", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/backtests/141");
    await page.getByRole("tab", { name: "Replay" }).click();
    await page.waitForTimeout(500);
    await page.keyboard.press(" ");
    await page.waitForTimeout(200);
    await page.keyboard.press(" ");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(300);

    await page.screenshot({
      path: "test-results/screenshots/backtests_141_replay.png",
      fullPage: true,
    });

    expect(errors, `console errors on replay: ${errors.join("; ")}`).toEqual([]);
  });

  test("replay mid-session is clipped and screenshots", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.goto("/backtests/141");
    await page.getByRole("tab", { name: "Replay" }).click();
    await page.waitForTimeout(400);
    for (let i = 0; i < 28; i++) await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(300);
    await page.screenshot({ path: "test-results/screenshots/backtests_141_replay_mid.png", fullPage: true });
    for (let i = 0; i < 6; i++) await page.keyboard.press("ArrowLeft");
    await page.getByRole("tab", { name: "Replay" }).focus();
    await page.keyboard.press("ArrowRight"); // must step the replay, not move tab focus
    await expect(page.getByRole("tab", { name: "Replay" })).toHaveAttribute("aria-selected", "true");
    expect(errors).toEqual([]);
  });

  test("diagnostics tab", async ({ page }) => {
    await page.goto("/backtests/141");
    await page.getByRole("tab", { name: "Diagnostics" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: "test-results/screenshots/backtests_141_diagnostics.png", fullPage: true });
  });

  test("nav rail reaches viewport bottom on tall viewport and when scrolled", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 1600 });
    await page.goto("/analytics");
    await page.waitForTimeout(500);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.screenshot({ path: "test-results/screenshots/analytics_1280x1600_bottom.png" });
    await page.setViewportSize({ width: 1280, height: 500 });
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.screenshot({ path: "test-results/screenshots/analytics_1280x500_scrolled.png" });
    const rail = await page.getByRole("navigation", { name: "Primary" }).boundingBox();
    expect(rail!.y + rail!.height).toBeGreaterThanOrEqual(499);
  });
});
