import { openLiveTools } from "./openLiveTools";
import { expect, test } from "@playwright/test";

test("pause, label source fields, persist dataset and resume the same capture", async ({
  page,
  request,
}, info) => {
  test.skip(!process.env.LATENCY_E2E, "Requires an isolated capture backend");
  await page.goto("/live");
  await openLiveTools(page);
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 32;
    canvas.getContext("2d")!.fillRect(0, 0, 64, 32);
    return canvas.toDataURL("image/jpeg").split(",")[1];
  });
  const response = await request.post("/api/capture/screen", {
    data: { sampling_mode: "adaptive" },
  });
  const id = (await response.json()).capture_id;
  const send = () =>
    request.post(`/api/capture/${id}/screen-frame`, {
      data: Buffer.from(encoded, "base64"),
    });
  const status = async () => await (await request.get("/api/capture")).json();
  try {
    await send();
    await expect
      .poll(async () => (await status()).frame?.frame_id)
      .toBeGreaterThan(0);
    const panel = page
      .locator("details.manual-correction")
      .filter({ hasText: "Corrección manual ·" });
    await panel.locator("summary").click();
    await panel.getByRole("button", { name: "Pausar análisis" }).click();
    await expect(
      panel.getByRole("button", { name: "Reanudar análisis" }),
    ).toBeVisible();
    const paused = await status();
    const observations = paused.observation_state.observations_seen;
    await send();
    await page.waitForTimeout(250);
    expect((await status()).observation_state.observations_seen).toBe(
      observations,
    );
    await panel.getByLabel("Cartas de Hero", { exact: true }).fill("As Kd");
    await panel.getByLabel("Board corregido").fill("2h 3c 4d");
    await panel.getByLabel("Jugador asiento 1", { exact: true }).fill("Hero");
    await panel.getByLabel("Stack asiento 1", { exact: true }).fill("100.25");
    await panel.getByLabel("Apuesta asiento 1", { exact: true }).fill("5.50");
    await panel
      .getByRole("combobox", { name: "Acción asiento 1", exact: true })
      .selectOption("FOLD");
    await panel
      .getByLabel("Motivo de la corrección")
      .fill("Corrección de la lectura de prueba");
    await panel.getByRole("button", { name: "Guardar corrección" }).click();
    await expect(panel.getByRole("status")).toHaveText(
      "Corrección guardada en el dataset.",
    );
    await expect(
      panel.getByLabel("Stack asiento 1", { exact: true }),
    ).toHaveValue("100.25");
    const corrected = await status();
    expect(corrected.capture_id).toBe(id);
    expect(corrected.observation_state.game_state.hero_cards).toEqual([
      "As",
      "Kd",
    ]);
    expect(corrected.observation_state.game_state.board).toEqual([
      "2h",
      "3c",
      "4d",
    ]);
    expect(corrected.observation_state.game_state.players[0].folded).toBe(true);
    const exported = await request.get(`/api/capture/${id}/corrections`);
    const rows = (await exported.json()).records;
    expect(rows).toHaveLength(1);
    expect(rows[0].before.hero_cards).toEqual([]);
    expect(rows[0].after.hero_cards).toEqual(["As", "Kd"]);
    const image = await request.get(
      `/api/capture/${id}/corrections/${rows[0].id}/frame`,
    );
    expect(image.status()).toBe(200);
    expect(image.headers()["x-frame-id"]).toBe(String(paused.frame.frame_id));
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 950 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await panel.screenshot({
        path: info.outputPath(`correction-${width}.png`),
      });
    }
    await panel.getByRole("button", { name: "Reanudar análisis" }).click();
    await expect(
      panel.getByRole("button", { name: "Pausar análisis" }),
    ).toBeVisible();
    await send();
    await expect
      .poll(async () => (await status()).observation_state.observations_seen)
      .toBeGreaterThan(observations);
    expect((await status()).capture_id).toBe(id);
    expect(
      (await (await request.get(`/api/capture/${id}/corrections`)).json())
        .records,
    ).toHaveLength(1);
  } finally {
    await request.post(`/api/capture/${id}/stop`);
  }
});
