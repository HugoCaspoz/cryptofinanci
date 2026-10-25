import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./training-tests",
  fullyParallel: false,
  workers: 1,
  outputDir: "test-results-training",
  use: {
    baseURL: process.env.TRAINING_E2E_URL || "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    channel: process.env.E2E_BROWSER_CHANNEL,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
