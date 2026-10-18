import { defineConfig } from '@playwright/test'

// The browser tests run against their own backend (:8010, mock market, mock clock, database
// "mystock_e2e") and their own Vite server (:5180), so they never touch the development data.
// PostgreSQL has to be running (`make db-up`).
const API_PORT = 8010
const WEB_PORT = 5180
const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://mystock:mystock@localhost:5432/mystock_e2e'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1, // one backend and one clock: the tests take turns
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 20_000 }, // alerts arrive with the 10-second polling
  reporter: [['list']],
  outputDir: '../e2e-shots/results',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `uv run uvicorn e2e.server:create_e2e_app --factory --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://localhost:${API_PORT}/api/health`,
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        E2E_MODE: '1',
        DATABASE_URL,
        APP_USERNAME: 'e2e',
        APP_PASSWORD: 'e2e-password',
        SECRET_KEY: 'e2e-secret-key-e2e-secret-key-0123456789',
        SESSION_MAX_AGE_SECONDS: String(30 * 24 * 3600), // the mock clock jumps a week ahead
        SCHEDULER_ENABLED: 'false',
        ADAPTER: 'mock',
      },
    },
    {
      command: `npm run dev -- --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: true,
      timeout: 60_000,
      env: { VITE_API_TARGET: `http://localhost:${API_PORT}` },
    },
  ],
})
