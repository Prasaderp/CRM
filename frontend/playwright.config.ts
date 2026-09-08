import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const frontendDirectory = path.dirname(fileURLToPath(import.meta.url));
const testDatabase =
  process.env.TEST_DATABASE_URL ??
  "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test";
const backendEnvironment = {
  ...process.env,
  ENVIRONMENT: "local",
  DATABASE_URL: testDatabase,
  TEST_DATABASE_URL: testDatabase,
  PUBLIC_ORIGIN: "http://127.0.0.1:5190",
  CANONICAL_NOTICE_VERSION: "2026-07-30",
  CANONICAL_NOTICE_TEXT: "Synthetic browser-test privacy notice.",
  SMTP_HOST: "127.0.0.1",
  SMTP_PORT: "1025",
  SMTP_SENDER: "browser-test@client.example",
  RECIPIENT_ALLOW_LIST: "browser-recipient@client.example",
  VITE_BACKEND_TARGET: "http://127.0.0.1:8019",
};

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./.playwright-artifacts",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [["line"]],
  use: {
    baseURL: "http://127.0.0.1:5190",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command:
        "uv run --project ../backend uvicorn real_estate_crm.app:app --host 127.0.0.1 --port 8019",
      cwd: frontendDirectory,
      env: backendEnvironment,
      url: "http://127.0.0.1:8019/health/live",
      timeout: 30_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5190",
      cwd: frontendDirectory,
      env: backendEnvironment,
      url: "http://127.0.0.1:5190",
      timeout: 30_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
