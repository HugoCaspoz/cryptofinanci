import {
  expect,
  type Page,
  type APIRequestContext,
  type TestInfo,
} from "@playwright/test";
import { resolve } from "node:path";

export async function verifyLiveStream(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
) {
  let httpPolls = 0;
  let connections = 0;
  let disconnect = () => {};
  let sendToPage: (text: string) => void = () => {};
  let lastSnapshot: any;
  let connectionSequence = 0;
  await page.route("**/api/capture", (route) => {
    httpPolls++;
    return route.abort();
  });
  await page.routeWebSocket("**/ws/live", (ws) => {
    connections++;
    const server = ws.connectToServer();
    disconnect = () => {
      ws.close();
      server.close();
    };
    sendToPage = (text) => ws.send(text);
    server.onMessage((message) => {
      const parsed = JSON.parse(String(message));
      connectionSequence = parsed.sequence;
      if (parsed.type === "capture.snapshot") lastSnapshot = parsed;
      ws.send(message);
    });
  });
  await page.goto("/live");
  await page.getByLabel("Asiento de Hero", { exact: true }).selectOption("1");
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/ocr-demo.avi"));
  const opening = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/capture/file") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  const started = await (await opening).json();
  await expect(page.getByTestId("current-pot")).toHaveText("750", {
    timeout: 10000,
  });
  await expect(page.getByTestId("current-hero-stack")).toHaveText("12500");
  await expect(page.getByTestId("current-street")).toHaveText("Flop");
  const other = await page.context().newPage();
  await other.route("**/api/capture", (route) => {
    httpPolls++;
    return route.abort();
  });
  try {
    await other.goto("/live");
    await expect(other.getByTestId("current-pot")).toHaveText("750");
    disconnect();
    await expect(
      page.getByText("Actualizaciones interrumpidas.", { exact: false }),
    ).toBeVisible();
    await expect(page.getByTestId("current-pot")).toHaveText("750");
    await expect(page.getByRole("banner").getByRole("status")).toHaveText(
      "Backend conectado",
      {
        timeout: 8000,
      },
    );
    await expect.poll(() => connections).toBeGreaterThanOrEqual(2);
    await expect(page.getByTestId("current-pot")).toHaveText("1500", {
      timeout: 12000,
    });
    await expect(other.getByTestId("current-pot")).toHaveText("1500");
    await expect(page.getByTestId("current-hero-stack")).toHaveText("12000");
    await expect(page.getByText("VÍDEO FINALIZADO · ÚLTIMO FRAME")).toBeVisible(
      { timeout: 12000 },
    );
    const final = await (await request.get("/api/capture")).json();
    expect(final.capture_id).toBe(started.capture_id);
    const events = page.getByRole("region", { name: "Eventos de la partida" });
    await expect(events.locator('[data-event-type="FLOP_DEALT"]')).toHaveCount(
      1,
    );
    // A delayed snapshot must not roll the capture back, even with a newer envelope.
    const old = structuredClone(lastSnapshot);
    old.sequence = connectionSequence + 1;
    old.payload.capture.revision = 0;
    old.payload.capture.observation_state.game_state.pot = "999999";
    sendToPage(JSON.stringify(old));
    sendToPage(JSON.stringify(old));
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await expect(page.getByTestId("current-pot")).toHaveText("1500");
    await expect(events.locator('[data-event-type="FLOP_DEALT"]')).toHaveCount(
      1,
    );
    expect(httpPolls).toBe(0);
    await page
      .locator(".live-table-grid")
      .screenshot({ path: info.outputPath("live-table-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page
      .locator(".live-table-grid")
      .screenshot({ path: info.outputPath("live-table-mobile.png") });
  } finally {
    await other.close();
  }
}
