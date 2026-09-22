import {
  expect,
  type Page,
  type APIRequestContext,
  type TestInfo,
} from "@playwright/test";
import { resolve } from "node:path";

export async function verifyHands(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
) {
  await page.goto("/live");
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/hands-demo.avi"));
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
  await expect(page.getByTestId("hands-started")).toHaveText("1", {
    timeout: 12000,
  });
  await expect(page.getByTestId("hands-finished")).toHaveText("1", {
    timeout: 22000,
  });
  await expect(page.getByTestId("hands-started")).toHaveText("2", {
    timeout: 12000,
  });
  await expect(page.getByText("VÍDEO FINALIZADO · ÚLTIMO FRAME")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByTestId("hand-status")).toHaveText("Incompleta");
  const capture = await (await request.get("/api/capture")).json();
  expect(capture.hand_storage.error).toBeNull();
  const list = await (await request.get(`/api/hands?scope_id=${scope}`)).json();
  expect(list.total).toBe(2);
  expect(list.items.map((hand: any) => hand.status).sort()).toEqual([
    "finished",
    "incomplete",
  ]);
  const completed = list.items.find((hand: any) => hand.status === "finished");
  const detail = await (
    await request.get(`/api/hands/${completed.hand_id}`)
  ).json();
  expect(detail.hand.state.board).toEqual(["Js", "7c", "4d"]);
  expect(
    detail.events.filter((event: any) => event.type === "HAND_FINISHED"),
  ).toHaveLength(1);
  expect(
    capture.observation_state.event_stream.events
      .filter((event: any) => event.type.startsWith("HAND_"))
      .map((event: any) => event.type),
  ).toEqual(["HAND_STARTED", "HAND_FINISHED", "HAND_STARTED"]);
  await page
    .getByRole("link", { name: "Ver manos guardadas de esta captura" })
    .click();
  await expect(
    page.getByText("2 manos guardadas en esta captura."),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("link", { name: "Mano 1 · Terminada" }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("hands-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Mano 1 · Terminada" }).click();
  await expect(
    page.getByRole("heading", { name: "Mano 1 · Terminada" }),
  ).toBeVisible();
  await expect(
    page.getByText(/Mano terminada/, { exact: false }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: info.outputPath("hand-mobile.png"),
    fullPage: true,
  });
}
