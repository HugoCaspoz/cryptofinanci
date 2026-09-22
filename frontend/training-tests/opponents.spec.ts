import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test("opponent opportunities update after real OCR actions and survive a finished hand", async ({
  page,
  request,
}, info) => {
  test.setTimeout(110000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/live");
  const panel = page.getByRole("region", { name: "Modelo de rivales" });
  await panel.getByLabel("Añadir contexto de torneo a esta mano").check();
  await panel.getByLabel("Buy-in", { exact: true }).fill("5");
  await panel.getByLabel("Stack inicial (fichas)").fill("10000");
  await panel.getByLabel("Participantes totales").fill("6");
  await panel.getByLabel("Jugadores restantes (opcional)").fill("6");
  await panel.getByLabel("Conozco la estructura completa de premios").check();
  await panel.getByLabel("Premio por puesto 1").fill("15");
  await panel.getByRole("button", { name: "Añadir tramo de premios" }).click();
  await panel.getByLabel("Premio por puesto 2").fill("9");
  await panel.getByRole("button", { name: "Añadir tramo de premios" }).click();
  await panel.getByLabel("Premio por puesto 3").fill("6");
  await panel.getByLabel("Usar un prior de población para este torneo").check();
  await panel.getByLabel("Nombre del supuesto").fill("Estudio 5 EUR");
  await panel.getByLabel("Prior VPIP del torneo (%)").fill("42");
  await panel.getByLabel("Prior PFR del torneo (%)").fill("10");
  await panel.getByLabel("Prior 3Bet del torneo (%)").fill("1");
  await page.setViewportSize({ width: 390, height: 844 });
  await panel
    .getByRole("group", { name: "Contexto del torneo" })
    .screenshot({ path: info.outputPath("tournament-form-mobile.png") });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/opponents-demo.avi"));
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  try {
    await expect(page.getByTestId("current-pot")).toHaveText("150", {
      timeout: 12000,
    });
    for (const seat of [3, 4, 5, 6])
      await panel.getByLabel(`Estadísticas asiento ${seat}`).uncheck();
    await panel.getByLabel("Botón para estadísticas").selectOption("1");
    await panel
      .getByLabel("Confirmo participantes e inicio sin acciones previas")
      .check();
    await panel
      .getByRole("button", { name: "Confirmar inicio para estadísticas" })
      .click();
    await expect(panel.getByRole("status")).toContainText("Inicio confirmado");
    await expect(panel.getByLabel("Torneo confirmado")).toContainText(
      "Total 30 EUR",
    );
    await expect(panel.getByLabel("Torneo confirmado")).toContainText(
      "Estudio 5 EUR",
    );
    await expect(panel.getByTestId("adaptive-range-2")).toContainText(
      "1326 combos",
    );
    const poker = page.getByRole("region", { name: "Motor matemático" });
    await poker.getByLabel("Hero para cálculos").selectOption("1");
    await poker.getByLabel("Origen de los rangos").selectOption("adaptive");
    await poker.getByLabel("Incluir asiento 2").check();
    await poker.getByLabel("Bote observado").selectOption("true");
    await poker.getByRole("button", { name: "Aplicar cálculo" }).click();
    await expect(poker.getByTestId("showdown-equity")).not.toHaveText("—", {
      timeout: 10000,
    });
    await expect(panel.getByTestId("opponent-actions-1")).toHaveText("1", {
      timeout: 23000,
    });
    await expect(panel.getByTestId("opponent-vpip-1")).toHaveText("—");
    await expect(panel.getByTestId("opponent-three_bet-2")).toHaveText(
      "100.0 %",
      { timeout: 14000 },
    );
    await expect(panel.getByTestId("opponent-vpip-1")).toHaveText("100.0 %", {
      timeout: 14000,
    });
    await expect(panel.getByTestId("adaptive-range-2")).toContainText(
      "three_bet",
    );
    await expect(panel.getByTestId("adaptive-range-2")).toContainText(
      "peso de datos 0.0 %",
    );
    await expect(panel.getByTestId("adaptive-range-2")).toContainText(
      "Peso del prior 100.0 %",
    );
    await expect(panel.getByTestId("adaptive-range-2")).toContainText(
      "tasa suavizada 1.0 %",
    );
    await expect(poker).toContainText("Rangos adaptativos hasta el evento");
    await expect(panel.getByTestId("opponent-fold_to_three_bet-1")).toHaveText(
      "0.0 %",
    );
    await expect(panel.getByTestId("opponent-cbet-2")).toHaveText("100.0 %", {
      timeout: 20000,
    });
    await expect(panel.getByTestId("opponent-fold_to_cbet-1")).toHaveText(
      "100.0 %",
      { timeout: 15000 },
    );
    await expect(panel.getByTestId("adaptive-range-2")).toContainText(
      "1176 combos",
    );
    await expect(panel.getByTestId("adaptive-range-1")).toContainText(
      "Retirado",
    );
    await expect(panel.getByTestId("opponent-wtsd-1")).toHaveText("0.0 %", {
      timeout: 15000,
    });
    await panel.screenshot({ path: info.outputPath("opponents-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await panel
      .getByRole("article", { name: "Perfil asiento 1" })
      .screenshot({ path: info.outputPath("opponent-mobile.png") });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    const current = await (await request.get("/api/opponents")).json();
    const archived = await (
      await request.get(`/api/opponents/archive/${current.analysis.scope_id}`)
    ).json();
    expect(
      archived.profiles.find((p: { seat: number }) => p.seat === 1).stats.wtsd
        .opportunities,
    ).toBe(1);
    expect(archived.adaptive.version).toBe("action-likelihood-v1");
    expect(archived.context.tournament.buy_in).toBe("5");
    expect(archived.adaptive.tournament.prize_pool).toBe("30");
    expect(archived.adaptive.history[1].evidence.prior_source.label).toBe(
      "Estudio 5 EUR",
    );
    expect(archived.adaptive.history[1].evidence.prior_strength).toBe(10);
    expect(
      archived.adaptive.history.map((h: { action: string }) => h.action),
    ).toEqual(["RAISE", "RAISE", "CALL", "BET", "FOLD"]);
    expect(
      archived.adaptive.ranges.find((r: { seat: number }) => r.seat === 2)
        .status,
    ).toBe("finished");
    await page.reload();
    await expect(panel.getByLabel("Torneo confirmado")).toContainText(
      "Estudio 5 EUR",
    );
    await expect(panel.getByLabel("Buy-in", { exact: true })).toHaveValue("5");
    expect(errors).toEqual([]);
  } finally {
    const capture = await (await request.get("/api/capture")).json();
    if (capture.capture_id)
      await request.post(`/api/capture/${capture.capture_id}/stop`);
  }
});
