import { openLiveTools } from "./openLiveTools";
import { chromium, expect, test } from "@playwright/test";
import { resolve } from "node:path";
import { existsSync } from "node:fs";
import { verifyCardRecognition } from "./card-scenario";
import { verifyOcr } from "./ocr-scenario";
import { verifyHands } from "./hands-scenario";
import { verifyActions } from "./actions-scenario";
import { verifyLiveStream } from "./live-scenario";

// One source per backend: capture scenarios must run sequentially.
test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  const current = await (await request.get("/api/capture")).json();
  expect(
    current.state,
    "Detén la captura antes de ejecutar las pruebas de captura",
  ).not.toBe("running");
  expect(
    existsSync(resolve("../sample_data/capture-demo.avi")),
    "Genera el vídeo con backend/scripts/create_sample_video.py antes de ejecutar estas pruebas",
  ).toBeTruthy();
  expect(
    existsSync(resolve("../sample_data/table-layout-demo.avi")),
    "Genera backend/scripts/create_layout_video.py antes de ejecutar las pruebas",
  ).toBeTruthy();
});

test.afterEach(async ({ request }) => {
  const current = await (await request.get("/api/capture")).json();
  if (current.capture_id)
    await request.post(`/api/capture/${current.capture_id}/stop`);
});

test("live state uses WebSocket, recovers after disconnect and stays synchronized across tabs", async ({
  page,
  request,
}, info) => {
  test.setTimeout(45000);
  await verifyLiveStream(page, request, info);
});

test("six actions are reconstructed from video and saved with evidence", async ({
  page,
  request,
}, info) => {
  test.setTimeout(85000);
  await verifyActions(page, request, info);
});

test("hands are separated, saved and remain available after reload", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  await verifyHands(page, request, info);
});

test("OCR stabilizes amounts and keeps the last reading during occlusion", async ({
  page,
  request,
}, info) => {
  test.setTimeout(40000);
  await verifyOcr(page, request, info);
});

test("cards are recognized from video and stable changes are emitted once", async ({
  page,
  request,
}, info) => {
  test.setTimeout(45000);
  await verifyCardRecognition(page, request, info);
});

test("file playback returns backend frames, persists through navigation and reaches EOF", async ({
  page,
  request,
}) => {
  await page.goto("/live");
  await openLiveTools(page);
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/capture-demo.avi"));
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  const preview = page.getByAltText("Frame recibido por el servidor");
  await expect(preview).toBeVisible();
  await expect
    .poll(async () =>
      preview.evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(960);
  await page.getByLabel("Mostrar regiones", { exact: true }).check();
  await expect(
    page.getByText("Overlay oculto: captura 960 × 540.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Regiones configuradas de la mesa" }),
  ).toHaveCount(0);
  await expect
    .poll(async () => Number(await page.getByTestId("frame-id").textContent()))
    .toBeGreaterThan(1);
  await expect(
    page.getByRole("button", { name: "Compartir pantalla o ventana" }),
  ).toBeDisabled();
  await page.getByRole("link", { name: "Sesiones", exact: true }).click();
  await page.getByRole("link", { name: "En directo", exact: true }).click();
  await expect(preview).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: "Depuración del pipeline" })
    .click();
  await expect
    .poll(async () =>
      Number(await page.getByTestId("capture-fps").textContent()),
    )
    .toBeGreaterThan(0);
  await expect
    .poll(async () =>
      Number(await page.getByTestId("processing-fps").textContent()),
    )
    .toBeGreaterThan(0);
  await expect(page.getByTestId("processing-latency")).toHaveText(/\d+\.\d ms/);
  const running = await (await request.get("/api/capture")).json();
  expect(running.pipeline.queue_size).toBeLessThanOrEqual(
    running.pipeline.queue_capacity,
  );
  expect(running.observation_state.observations_seen).toBe(
    running.pipeline.processed_frames,
  );
  expect(running.observation_state.recognition_available).toBe(false);
  await page.screenshot({
    path: test.info().outputPath("file-capture.png"),
    fullPage: true,
  });
  await expect(page.getByText("VÍDEO FINALIZADO · ÚLTIMO FRAME")).toBeVisible({
    timeout: 15000,
  });
  const state = await (await request.get("/api/capture")).json();
  expect(state.frame.frame_id).toBeLessThanOrEqual(65);
  expect(state.frame.timestamp).toBeGreaterThan(10);
  expect(state.capture_fps).toBe(5);
  expect(state.pipeline.active).toBe(false);
  expect(state.pipeline.queue_size).toBe(0);
  expect(state.pipeline.capture_fps).toBe(0);
  expect(state.pipeline.processed_frames + state.pipeline.dropped_frames).toBe(
    state.pipeline.captured_frames,
  );
  expect(state.observation_state.last_frame_id).toBe(state.frame.frame_id);
});

test("layout overlay follows the original frame and edits survive reload", async ({
  page,
  request,
}) => {
  const originalResponse = await request.get("/api/table-layout");
  const original = await originalResponse.json();
  try {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/live");
    await openLiveTools(page);
    await page
      .getByLabel("Archivo de vídeo")
      .setInputFiles(resolve("../sample_data/table-layout-demo.avi"));
    await page.getByRole("button", { name: "Reproducir archivo" }).click();
    await expect(
      page.getByAltText("Frame recibido por el servidor"),
    ).toBeVisible();
    await page.getByLabel("Mostrar regiones", { exact: true }).check();
    const overlay = page.getByRole("img", {
      name: "Regiones configuradas de la mesa",
    });
    await expect(overlay).toBeVisible();
    await expect(overlay.locator("rect")).toHaveCount(29);
    await expect(overlay.locator("text")).toHaveCount(29);
    await expect(
      page.getByText("VÍDEO FINALIZADO · ÚLTIMO FRAME"),
    ).toBeVisible();
    const state = await (await request.get("/api/capture")).json();
    const jpeg = await request.get(`/api/capture/${state.capture_id}/frame`);
    expect(jpeg.headers()["x-frame-width"]).toBe("1920");
    expect(jpeg.headers()["x-frame-height"]).toBe("1080");

    async function checkGeometry() {
      const error = await page.evaluate(() => {
        const img =
          document.querySelector<HTMLImageElement>(".preview-stage img")!;
        const imageBox = img.getBoundingClientRect();
        const scale = Math.min(imageBox.width / 1920, imageBox.height / 1080);
        const originX = imageBox.x + (imageBox.width - 1920 * scale) / 2;
        const originY = imageBox.y + (imageBox.height - 1080 * scale) / 2;
        return Math.max(
          ...Array.from(
            document.querySelectorAll<SVGRectElement>(".table-overlay rect"),
          ).flatMap((rect) => {
            const box = rect.getBoundingClientRect();
            return [
              Math.abs(box.x - originX - rect.x.baseVal.value * scale),
              Math.abs(box.y - originY - rect.y.baseVal.value * scale),
              Math.abs(box.width - rect.width.baseVal.value * scale),
              Math.abs(box.height - rect.height.baseVal.value * scale),
            ];
          }),
        );
      });
      expect(error).toBeLessThan(1);
    }
    await checkGeometry();
    await page.screenshot({
      path: test.info().outputPath("layout-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await checkGeometry();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: test.info().outputPath("layout-mobile.png"),
      fullPage: true,
    });
    await page.getByLabel("Mostrar etiquetas").uncheck();
    await expect(overlay.locator("text")).toHaveCount(0);
    await expect(overlay.locator("rect")).toHaveCount(29);

    await page.getByRole("spinbutton", { name: "X", exact: true }).fill("1920");
    await expect(
      page.getByRole("button", { name: "Guardar layout" }),
    ).toBeDisabled();
    await expect(overlay).toHaveCount(0);
    const x =
      (original.regions.hero_cards.x + 10) %
      (1921 - original.regions.hero_cards.width);
    await page
      .getByRole("spinbutton", { name: "X", exact: true })
      .fill(String(x));
    await expect(
      overlay.locator('[data-region="hero_cards"] rect'),
    ).toHaveAttribute("x", String(x));
    await page.getByRole("button", { name: "Guardar layout" }).click();
    await expect(page.getByText("Layout guardado.")).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("spinbutton", { name: "X", exact: true }),
    ).toHaveValue(String(x));
    await expect(
      page.getByRole("button", { name: "Guardar layout" }),
    ).toBeDisabled();

    // Another tab wins. The old tab must retain its draft without overwriting it.
    const latest = await request.get("/api/table-layout");
    const competing = {
      ...(await latest.json()),
      platform: "Concurrent test edit",
    };
    expect(
      (
        await request.put("/api/table-layout", {
          data: competing,
          headers: { "If-Match": latest.headers().etag },
        })
      ).ok(),
    ).toBeTruthy();
    await page.getByLabel("Plataforma", { exact: true }).fill("Old tab edit");
    await page.getByRole("button", { name: "Guardar layout" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "La configuración cambió",
    );
    await expect(page.getByLabel("Plataforma", { exact: true })).toHaveValue(
      "Old tab edit",
    );
    await page
      .getByRole("button", { name: "Descartar cambios y recargar" })
      .click();
    await expect(page.getByLabel("Plataforma", { exact: true })).toHaveValue(
      "Concurrent test edit",
    );
  } finally {
    const latest = await request.get("/api/table-layout");
    const restored = await request.put("/api/table-layout", {
      data: original,
      headers: { "If-Match": latest.headers().etag },
    });
    expect(restored.ok()).toBeTruthy();
  }
});

test("invalid video is rejected and cancelled sharing leaves no active source", async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getDisplayMedia = async () => {
      throw new DOMException("Denied", "NotAllowedError");
    };
  });
  await page.goto("/live");
  await openLiveTools(page);
  await page.getByLabel("Archivo de vídeo").setInputFiles({
    name: "broken.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("not a video"),
  });
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "No se puede abrir el vídeo",
  );
  await page
    .getByRole("button", { name: "Compartir pantalla o ventana" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "No se compartió ninguna pantalla",
  );
  expect((await (await request.get("/api/capture")).json()).state).not.toBe(
    "running",
  );
});

test("native browser tab sharing reaches backend and stops cleanly", async ({
  baseURL,
  request,
}) => {
  test.setTimeout(45000);
  const browser = await chromium.launch({
    channel: "chromium",
    args: ["--auto-select-tab-capture-source-by-title=Zeros capture fixture"],
  });
  try {
    const context = await browser.newContext({ baseURL });
    const target = await context.newPage();
    await target.goto("/");
    await target.setContent(
      '<html><head><title>Zeros capture fixture</title></head><body style="background:#204020;color:#d0f0b0;font:40px sans-serif;padding:60px"><h1>ZEROS — SCREEN TEST</h1><p id="clock"></p><script>setInterval(()=>document.querySelector("#clock").textContent=Date.now(),100)</script></body></html>',
    );
    const page = await context.newPage();
    await page.goto("/live");
    await openLiveTools(page);
    await page.getByLabel("FPS de captura").selectOption("2");
    await page
      .getByRole("button", { name: "Compartir pantalla o ventana" })
      .click();
    await expect(
      page.getByAltText("Frame recibido por el servidor"),
    ).toBeVisible({ timeout: 15000 });
    await expect
      .poll(async () =>
        Number(await page.getByTestId("frame-id").textContent()),
      )
      .toBeGreaterThan(1);
    const state = await (await request.get("/api/capture")).json();
    expect(state.source).toBe("screen");
    expect(state.capture_fps).toBe(2);
    await page.screenshot({
      path: test.info().outputPath("screen-capture.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page
      .locator("summary")
      .filter({ hasText: "Depuración del pipeline" })
      .click();
    await expect(page.getByTestId("queue-size")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: test.info().outputPath("screen-mobile.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Detener captura" }).click();
    await expect(
      page.getByAltText("Frame recibido por el servidor"),
    ).toHaveCount(0);
    expect((await (await request.get("/api/capture")).json()).state).toBe(
      "stopped",
    );
    await page
      .getByRole("button", { name: "Compartir pantalla o ventana" })
      .click();
    await expect(
      page.getByAltText("Frame recibido por el servidor"),
    ).toBeVisible();
    await target.close();
    await expect(
      page.getByAltText("Frame recibido por el servidor"),
    ).toHaveCount(0);
    expect((await (await request.get("/api/capture")).json()).state).toBe(
      "stopped",
    );
  } finally {
    await browser.close();
  }
});
