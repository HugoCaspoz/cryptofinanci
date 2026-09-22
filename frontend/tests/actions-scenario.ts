import {
  expect,
  type Page,
  type APIRequestContext,
  type TestInfo,
} from "@playwright/test";
import { resolve } from "node:path";

export async function verifyActions(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
) {
  await page.goto("/live");
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/actions-demo.avi"));
  const opening = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/capture/file") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  const opened = await opening;
  expect(opened.status()).toBe(201);
  const scope = (await opened.json()).observation_state.game_state.scope_id;
  await expect(
    page.getByRole("button", { name: "Detener captura" }),
  ).toBeEnabled();
  await expect(page.getByTestId("action-summary")).toHaveText(
    "6 acciones reconstruidas en esta captura.",
    { timeout: 58000 },
  );
  await expect(page.getByText("VÍDEO FINALIZADO · ÚLTIMO FRAME")).toBeVisible({
    timeout: 10000,
  });
  const capture = await (await request.get("/api/capture")).json();
  expect(capture.hand_storage.error).toBeNull();
  const game = capture.observation_state.game_state;
  expect(game.scope_id).toBe(scope);
  expect(game.players[4].folded).toBe(true);
  expect(game.players[5].all_in).toBe(true);
  const archived = await (
    await request.get(`/api/hands/${game.hand_id}`)
  ).json();
  const actions = archived.events.filter((e: any) =>
    e.type.startsWith("PLAYER_"),
  );
  expect(actions.map((e: any) => e.type)).toEqual([
    "PLAYER_CHECKED",
    "PLAYER_BET",
    "PLAYER_CALLED",
    "PLAYER_RAISED",
    "PLAYER_FOLDED",
    "PLAYER_ALL_IN",
  ]);
  expect(actions.map((e: any) => e.amount)).toEqual([
    null,
    "500",
    "500",
    "1000",
    null,
    "1000",
  ]);
  expect(archived.hand.status).toBe("incomplete");
  expect(
    actions.every(
      (e: any) => e.action_evidence.length === 5 && e.confidence >= 0.8,
    ),
  ).toBe(true);
  await page.goto(`/hands/${game.hand_id}`);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Mano 1 · Incompleta" }),
  ).toBeVisible();
  await expect(page.getByText(/Asiento 4 · Apuesta total 1000/)).toBeVisible();
  await page
    .getByText(/Asiento 6 · Apuesta total 1000/)
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("actions-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: info.outputPath("actions-mobile.png"),
    fullPage: true,
  });
}
