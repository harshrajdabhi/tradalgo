import { defineConfig } from "@playwright/test";

// Real-API parity run: the built app is served by the FastAPI process itself (not Vite),
// against a throwaway seeded data dir. Never touches data/tradalgo.db.
const OUT = "test-results/api-e2e";

export default defineConfig({
  testDir: "./e2e/api",
  timeout: 30000,
  workers: 1,
  webServer: {
    command:
      `../.venv/bin/python e2e/api/seed.py ${OUT} && ` +
      `TRADALGO_CONFIG=$PWD/${OUT}/config.yaml ../.venv/bin/python -m uvicorn tradalgo.api.app:app ` +
      `--host 127.0.0.1 --port 8599`,
    url: "http://127.0.0.1:8599/api/health",
    reuseExistingServer: false,
    timeout: 60000,
  },
  use: { baseURL: "http://127.0.0.1:8599" },
});
