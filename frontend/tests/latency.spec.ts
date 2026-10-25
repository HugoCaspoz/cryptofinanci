import { openLiveTools } from "./openLiveTools";
import { test, expect } from "@playwright/test";
import { LatencyWindow } from "../src/live/latency";

// An isolated backend is required: one capture source exists per instance.
test("browser latency statistics are bounded and reject invalid durations", () => {
  const window = new LatencyWindow();
  expect(window.add(Number.NaN, 1)).toBeNull();
  expect(window.add(-1, 1)).toBeNull();
  let result = window.add(100, 1)!;
  expect(result.within_target).toBe(false);
  for (let i = 0; i < 10000; i++) result = window.add(i, i)!;
  expect(result.samples).toBe(128);
  expect(result.total_samples).toBe(10001);
  expect(result.p95_ms).toBe(9993);
});

test("latency stages update from WebSocket without polling capture and fit mobile", async ({
  page,
  request,
}, info) => {
  test.skip(!process.env.LATENCY_E2E, "Requires the isolated latency backend");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const polled: string[] = [];
  page.on("request", (item) => {
    if (
      new URL(item.url()).pathname === "/api/capture" &&
      item.method() === "GET"
    )
      polled.push(item.url());
  });
  await page.goto("/live");
  await openLiveTools(page);
  await page
    .locator("summary")
    .filter({ hasText: "Depuración del pipeline" })
    .click();
  // A JPEG fixture is created in-browser; no screen-selection permission is needed.
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 64;
    canvas.getContext("2d")!.fillRect(0, 0, 64, 64);
    return canvas.toDataURL("image/jpeg").split(",")[1];
  });
  const start = await request.post("/api/capture/screen", {
    data: { capture_fps: 15 },
  });
  expect(start.status()).toBe(201);
  const identity = (await start.json()).capture_id;
  try {
    for (let i = 0; i < 12; i++) {
      expect(
        (
          await request.post(`/api/capture/${identity}/screen-frame`, {
            data: Buffer.from(encoded, "base64"),
            headers: { "Content-Type": "image/jpeg" },
          })
        ).status(),
      ).toBe(204);
      await page.waitForTimeout(90);
    }
    for (const name of [
      "capture",
      "vision",
      "preview",
      "state",
      "publish",
      "total_backend",
      "ui",
    ]) {
      await expect(page.getByTestId(`latency-${name}`)).toContainText(
        /\d+\.\d ms/,
      );
    }
    await expect(page.getByTestId("latency-vision")).toContainText("< 200 ms");
    await expect(page.getByTestId("latency-state")).toContainText("< 50 ms");
    await expect(page.getByTestId("latency-ui")).toContainText("< 100 ms");
    const snapshot = await (await request.get("/api/capture")).json();
    await expect(page.getByTestId("session-health")).toContainText("MiB RSS");
    for (const [key, count] of Object.entries(
      snapshot.session_health.retained,
    )) {
      expect(Number(count)).toBeLessThanOrEqual(
        snapshot.session_health.limits[key],
      );
    }
    expect(snapshot.pipeline.latencies.state.samples).toBeGreaterThan(0);
    expect(snapshot.pipeline.latencies.state.frame_id).toBe(
      snapshot.frame.frame_id,
    );
    expect(snapshot.observation_state.observations_seen).toBe(
      snapshot.pipeline.processed_frames,
    );
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 950 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page
        .locator(".pipeline-debug")
        .filter({ hasText: "Depuración del pipeline" })
        .screenshot({ path: info.outputPath(`latency-${width}.png`) });
    }
    expect(polled).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await request.post(`/api/capture/${identity}/stop`);
  }
});
