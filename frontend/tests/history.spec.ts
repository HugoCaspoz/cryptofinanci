import { openLiveTools } from "./openLiveTools";
import { expect, test } from "@playwright/test";

test("temporal history restores source images without replaying analysis and resets across captures", async ({
  page,
  request,
}, info) => {
  test.skip(!process.env.LATENCY_E2E, "Requires an isolated backend");
  await page.goto("/live");
  await openLiveTools(page);
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 32;
    canvas.getContext("2d")!.fillRect(0, 0, 64, 32);
    return canvas.toDataURL("image/jpeg").split(",")[1];
  });
  const started = await request.post("/api/capture/screen", {
    data: { sampling_mode: "adaptive" },
  });
  const id = (await started.json()).capture_id;
  try {
    for (let i = 0; i < 15; i++) {
      expect(
        (
          await request.post(`/api/capture/${id}/screen-frame`, {
            data: Buffer.from(encoded, "base64"),
          })
        ).status(),
      ).toBe(204);
      await page.waitForTimeout(115);
    }
    await request.post(`/api/capture/${id}/stop`);
    const before = await (await request.get("/api/capture")).json();
    expect(before.pipeline.buffer.frames).toBeGreaterThan(
      before.pipeline.captured_frames,
    );
    await page
      .locator("summary")
      .filter({ hasText: "Historial temporal de imágenes" })
      .click();
    const history = page
      .locator("details.pipeline-debug")
      .filter({ hasText: "Historial temporal de imágenes" });
    await history.getByRole("button", { name: "Actualizar historial" }).click();
    const indexResponse = await request.get(`/api/capture/${id}/buffer`);
    expect(indexResponse.headers()["cache-control"]).toBe("no-store");
    const entries = (await indexResponse.json()).frames;
    const slider = history.getByRole("slider", { name: "Frame del historial" });
    await slider.fill("0");
    const image = history.getByRole("img");
    await expect(image).toHaveAttribute(
      "src",
      `/api/capture/${id}/buffer/frames/${entries[0].frame_id}`,
    );
    await expect
      .poll(() =>
        image.evaluate((element: HTMLImageElement) => element.naturalWidth),
      )
      .toBe(64);
    const earlier = await request.get(
      `/api/capture/${id}/buffer/frame?timestamp=${entries[1].timestamp - 0.000001}`,
    );
    expect(earlier.headers()["x-frame-id"]).toBe(String(entries[0].frame_id));
    const after = await (await request.get("/api/capture")).json();
    expect(after.pipeline.processed_frames).toBe(
      before.pipeline.processed_frames,
    );
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 950 });
      await expect(history).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await history.screenshot({
        path: info.outputPath(`history-${width}.png`),
      });
    }
    await page.route(`**/buffer/frames/${entries[1].frame_id}`, (route) =>
      route.fulfill({ status: 404 }),
    );
    await slider.fill("1");
    await expect(history.getByRole("alert")).toContainText(
      "ya no está disponible",
    );
    await page.unroute(`**/buffer/frames/${entries[1].frame_id}`);
    await history.getByRole("button", { name: "Actualizar historial" }).click();
    await expect(history.getByRole("alert")).toHaveCount(0);
    const next = await request.post("/api/capture/screen", { data: {} });
    const nextId = (await next.json()).capture_id;
    try {
      await expect(history.getByRole("img")).toHaveCount(0);
      expect((await request.get(`/api/capture/${id}/buffer`)).status()).toBe(
        409,
      );
    } finally {
      await request.post(`/api/capture/${nextId}/stop`);
    }
  } finally {
    await request.post(`/api/capture/${id}/stop`);
  }
});
