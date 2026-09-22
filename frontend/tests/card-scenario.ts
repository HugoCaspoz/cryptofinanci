import {
  expect,
  type APIRequestContext,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { resolve } from "node:path";

export async function verifyCardRecognition(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
) {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/live");
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/cards-demo.avi"));
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  await expect(page.getByTestId("hero-card")).toHaveCount(2, { timeout: 8000 });
  await expect(page.getByTestId("hero-card").first()).toHaveAttribute(
    "aria-label",
    "A♠",
  );
  await expect(
    page.getByText("Referencias de demostración", { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("card-event-count")).toHaveText("1");
  await expect(page.getByTestId("board-card")).toHaveCount(3, {
    timeout: 8000,
  });
  await expect(page.getByTestId("board-card")).toHaveCount(4, {
    timeout: 8000,
  });
  await expect(page.getByTestId("board-card")).toHaveCount(5, {
    timeout: 8000,
  });
  await expect(page.getByTestId("card-event-count")).toHaveText("4");
  const eventPanel = page.getByRole("region", {
    name: "Eventos de la partida",
  });
  await expect(
    eventPanel.locator('[data-event-type="FLOP_DEALT"]'),
  ).toHaveCount(1);
  await expect(
    eventPanel.locator('[data-event-type="TURN_DEALT"]'),
  ).toHaveCount(1);
  await expect(
    eventPanel.locator('[data-event-type="RIVER_DEALT"]'),
  ).toHaveCount(1);
  await eventPanel.screenshot({ path: info.outputPath("events-desktop.png") });
  await page
    .getByRole("region", { name: "Reconocimiento de cartas" })
    .screenshot({ path: info.outputPath("cards-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await eventPanel.screenshot({ path: info.outputPath("events-mobile.png") });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page
    .getByRole("region", { name: "Reconocimiento de cartas" })
    .screenshot({ path: info.outputPath("cards-mobile.png") });
  await expect(page.getByText("VÍDEO FINALIZADO · ÚLTIMO FRAME")).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByTestId("card-event-count")).toHaveText("7");
  await expect(page.getByTestId("board-card")).toHaveCount(0);
  await expect(page.getByTestId("hero-card")).toHaveCount(2);
  const state = await (await request.get("/api/capture")).json();
  const cards = state.observation_state.cards;
  expect(cards.events.map((event: { type: string }) => event.type)).toEqual([
    "HOLE_CARDS_DETECTED",
    "FLOP_DEALT",
    "TURN_DEALT",
    "RIVER_DEALT",
    "HERO_CARDS_CLEARED",
    "BOARD_CARDS_CLEARED",
    "HOLE_CARDS_DETECTED",
  ]);
  expect(
    cards.events.every(
      (event: { frame_id: number }) => event.frame_id <= state.frame.frame_id,
    ),
  ).toBeTruthy();
  expect(state.observation_state.recognition_available).toBe(true);
  const stream = state.observation_state.event_stream;
  const exportedResponse = await request.get(
    `/api/events?scope_id=${stream.scope_id}`,
  );
  expect(exportedResponse.ok()).toBeTruthy();
  const exported = await exportedResponse.json();
  expect(exported.gap).toBe(false);
  expect(
    exported.events
      .filter(
        (event: any) =>
          ![
            "GAME_STATE_UPDATED",
            "HAND_STARTED",
            "HAND_FINISHED",
            "CAPTURE_ENDED",
          ].includes(event.type),
      )
      .map((event: any) => event.type),
  ).toEqual(cards.events.map((event: any) => event.type));
  expect(exported.events.map((event: any) => event.sequence)).toEqual(
    Array.from({ length: stream.event_count }, (_, i) => i + 1),
  );
  expect(exported.events.at(-1).state_after.hero_cards).toEqual(["As", "Jh"]);
  expect(exported.events.at(-1).state_after.board).toEqual([]);
  expect(
    exported.events.every((event: any) => event.amount === null),
  ).toBeTruthy();
  const downloadPromise = page.waitForEvent("download");
  await eventPanel
    .getByRole("link", { name: "Exportar historial disponible (JSON)" })
    .click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(
    `zeros-events-${stream.scope_id}.json`,
  );
  expect(await download.failure()).toBeNull();
  expect(browserErrors).toEqual([]);
}
