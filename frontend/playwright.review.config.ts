import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./review-tests",
  workers: 1,
  outputDir: "test-results-review",
  use: {
    baseURL: process.env.REVIEW_E2E_URL || "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
