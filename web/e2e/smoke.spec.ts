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
});
