import { openLiveTools } from "./openLiveTools";
import { expect, test } from "@playwright/test";

test("adaptive sampling bursts on change and returns to two FPS", async ({
  page,
  request,
}) => {
  test.skip(!process.env.LATENCY_E2E, "Requires an isolated capture backend");
  await page.goto("/live");
  await openLiveTools(page);
  await expect(page.getByLabel("FPS de captura")).toHaveValue("0");
  const images = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 64;
    const context = canvas.getContext("2d")!;
    return ["black", "white"].map((color) => {
      context.fillStyle = color;
      context.fillRect(0, 0, 64, 64);
      return canvas.toDataURL("image/jpeg").split(",")[1];
    });
  });
  expect(
    (
      await request.post("/api/capture/screen", {
        data: { sampling_mode: "unknown" },
      })
    ).status(),
  ).toBe(422);
  const response = await request.post("/api/capture/screen", {
    data: { sampling_mode: "adaptive", capture_fps: 1 },
  });
  expect(response.status()).toBe(201);
  const id = (await response.json()).capture_id;
  const status = async () =>
    (await (await request.get("/api/capture")).json()).pipeline;
  const send = async (image: string) => {
    expect(
      (
        await request.post(`/api/capture/${id}/screen-frame`, {
          data: Buffer.from(image, "base64"),
          headers: { "Content-Type": "image/jpeg" },
        })
      ).status(),
    ).toBe(204);
    await page.waitForTimeout(115);
  };
  try {
    for (let i = 0; i < 10; i++) await send(images[0]);
    let metrics = await status();
    expect(metrics.sampling.target_fps).toBe(2);
    expect(metrics.sampling.skipped_frames).toBeGreaterThan(3);
    await send(images[1]);
    await expect
      .poll(async () => (await status()).sampling.target_fps)
      .toBe(10);
    for (let i = 0; i < 22; i++) await send(images[1]);
    await expect.poll(async () => (await status()).sampling.target_fps).toBe(2);
    metrics = await status();
    expect(metrics.sampling.observed_frames).toBe(
      metrics.captured_frames + metrics.sampling.skipped_frames,
    );
    expect(metrics.queue_high_watermark).toBeLessThanOrEqual(
      metrics.queue_capacity,
    );
    await page
      .locator("summary")
      .filter({ hasText: "Depuración del pipeline" })
      .click();
    await expect(page.getByText(/Muestreo inteligente: 2 FPS/)).toBeVisible();
  } finally {
    await request.post(`/api/capture/${id}/stop`);
  }
  const restart = await request.post("/api/capture/screen", {
    data: { sampling_mode: "adaptive" },
  });
  const next = await restart.json();
  try {
    expect(next.pipeline.sampling.observed_frames).toBe(0);
    expect(next.pipeline.sampling.skipped_frames).toBe(0);
    expect(next.pipeline.sampling.target_fps).toBe(2);
  } finally {
    await request.post(`/api/capture/${next.capture_id}/stop`);
  }
});
