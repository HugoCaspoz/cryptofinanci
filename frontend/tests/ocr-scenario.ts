import {
  expect,
  type APIRequestContext,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { resolve } from "node:path";

export async function verifyOcr(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/live");
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/ocr-demo.avi"));
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  await expect(page.getByTestId("ocr-pot")).toHaveText("750", {
    timeout: 8000,
  });
  await expect(page.getByTestId("ocr-players.0.nickname")).toHaveText("Alice");
  await expect(page.getByTestId("ocr-players.0.stack")).toHaveText("12500");
  await expect(page.getByTestId("ocr-players.0.bet")).toHaveText("0");
  await expect(page.getByTestId("ocr-blinds")).toHaveText("50 / 100");
  await expect(page.getByTestId("game-pot")).toHaveText("750");
  await expect(page.getByTestId("game-street")).toHaveText("Flop");
  await expect(page.getByTestId("game-hero")).toHaveText("A♠ · J♥");
  await expect(page.getByTestId("game-board")).toHaveText("J♠ · 7♣ · 4♦");
  await expect(page.getByTestId("game-stack-1")).toHaveText("12500");
  const initialGame = (await (await request.get("/api/capture")).json())
    .observation_state.game_state;
  await expect
    .poll(
      async () => {
        const state = await (await request.get("/api/capture")).json();
        return state.observation_state.ocr.fields.pot.status;
      },
      { timeout: 8000 },
    )
    .toBe("unknown");
  await expect(page.getByTestId("ocr-pot")).toHaveText("750");
  await expect(page.getByTestId("game-pot").locator("..")).toContainText(
    "Último valor",
  );
  const obscuredGame = (await (await request.get("/api/capture")).json())
    .observation_state.game_state;
  expect(obscuredGame.revision).toBe(initialGame.revision);
  await expect(page.getByTestId("ocr-pot").locator("..")).toContainText(
    "Último valor conservado",
  );
  await expect(page.getByTestId("ocr-pot")).toHaveText("1500", {
    timeout: 10000,
  });
  await expect(page.getByTestId("ocr-players.0.stack")).toHaveText("12000");
  await expect(page.getByTestId("ocr-players.0.bet")).toHaveText("500");
  await expect(page.getByTestId("game-pot")).toHaveText("1500");
  await expect(page.getByTestId("game-stack-1")).toHaveText("12000");
  await expect(page.getByTestId("game-bet-1")).toHaveText("500");
  const gamePanel = page.getByRole("region", { name: "Estado de la partida" });
  await gamePanel.locator("summary").click();
  await gamePanel.screenshot({ path: info.outputPath("game-desktop.png") });
  const panel = page.getByRole("region", { name: "Lectura OCR de la mesa" });
  await panel.screenshot({ path: info.outputPath("ocr-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByText("Ver lecturas originales y confianza", { exact: true })
    .click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await panel.screenshot({ path: info.outputPath("ocr-mobile.png") });
  await gamePanel.screenshot({ path: info.outputPath("game-mobile.png") });
  await expect(page.getByText("VÍDEO FINALIZADO · ÚLTIMO FRAME")).toBeVisible({
    timeout: 10000,
  });
  const result = await (await request.get("/api/capture")).json();
  expect(result.observation_state.ocr.status).toBe("ready");
  expect(
    Object.values(result.observation_state.ocr.fields).every(
      (field: any) => field.status === "confirmed",
    ),
  ).toBeTruthy();
  expect(result.pipeline.queue_high_watermark).toBeLessThanOrEqual(2);
  expect(result.observation_state.cards.event_count).toBe(2);
  const game = result.observation_state.game_state;
  expect(game.hand_id).toBeTruthy();
  expect(game.hand_status).toBe("incomplete");
  expect(game.current_player).toBeNull();
  expect(game.button_position).toBeNull();
  expect(game.players[0].player_id).toBe(initialGame.players[0].player_id);
  expect(game.players[0].all_in).toBeNull();
  const potChanges = game.events
    .flatMap((event: any) => event.changes)
    .filter((change: any) => change.field === "pot");
  expect(potChanges).toEqual([
    { field: "pot", previous: null, current: "750" },
    { field: "pot", previous: "750", current: "1500" },
  ]);
  await request.post(`/api/capture/${result.capture_id}/stop`);
  const restarted = await (
    await request.post("/api/capture/screen", { data: {} })
  ).json();
  expect(restarted.observation_state.game_state.pot).toBeNull();
  expect(restarted.observation_state.game_state.revision).toBe(0);
  expect(restarted.observation_state.event_stream.event_count).toBe(0);
  expect(
    (await request.get(`/api/events?scope_id=${game.scope_id}`)).status(),
  ).toBe(409);
  expect(restarted.observation_state.game_state.scope_id).not.toBe(
    game.scope_id,
  );
  expect(errors).toEqual([]);
}
