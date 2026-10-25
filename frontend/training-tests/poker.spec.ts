import { openLiveTools } from "../tests/openLiveTools";
import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test.describe.configure({ mode: "serial" });

for (const mobile of [false, true]) {
  test(`math updates from real OCR and WebSocket (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(45000);
    expect((await (await request.get("/health")).json()).mode).toBe("TRAINING");
    await page.setViewportSize(
      mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
    );
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/live");
  await openLiveTools(page);
    await page
      .getByLabel("Archivo de vídeo")
      .setInputFiles(resolve("../sample_data/ocr-demo.avi"));
    await page.getByRole("button", { name: "Reproducir archivo" }).click();
    await expect(page.getByTestId("current-pot")).toHaveText("750", {
      timeout: 12000,
    });
    const panel = page.getByRole("region", { name: "Motor matemático" });
    try {
      await panel.getByLabel("Hero para cálculos").selectOption("2");
      await panel.getByLabel("Bote observado").selectOption("true");
      await panel.getByLabel("Incluir asiento 1").check();
      await panel.getByLabel("Rango del asiento 1").fill("QQ,KK,AKs");
      await panel.getByLabel("Rango de Hero para comparar").fill("JJ,AA,AK");
      await panel.getByLabel("Botón postflop").selectOption("2");
      await panel
        .getByLabel("Confirmo el contexto postflop para esta mano")
        .check();
      await panel.getByRole("button", { name: "Aplicar cálculo" }).click();
      await expect(panel.getByTestId("showdown-equity")).toContainText("%", {
        timeout: 12000,
      });
      await expect(
        page.getByLabel("Asiento de Hero", { exact: true }),
      ).toHaveValue("2");
      await expect(panel.getByTestId("required-equity")).toHaveText("25.0 %", {
        timeout: 20000,
      });
      const result = await (await request.get("/api/poker")).json();
      expect(result.analysis.metrics.pot_size).toBe("1500");
      expect(result.analysis.metrics.effective_stack).toBe("12000");
      expect(result.analysis.metrics.spr).toBe(8);
      const postflop = panel.getByRole("region", { name: "Análisis postflop" });
      await expect(postflop.getByTestId("postflop-hand")).toHaveText("Pareja");
      await expect(
        postflop.getByText("Top pair", { exact: true }),
      ).toBeVisible();
      await expect(postflop.getByTestId("postflop-position")).toHaveText(
        "Último en actuar",
      );
      await expect(postflop.getByTestId("range-equity")).toContainText("%");
      expect(
        result.analysis.postflop.range_comparison.hero.available_combos,
      ).toBeGreaterThan(0);
      await postflop.screenshot({ path: info.outputPath("postflop.png") });
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath("poker.png"),
        fullPage: true,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
      expect(errors).toEqual([]);
      // Changing range clears the result and rejects blocked combos without fabricating equity.
      await panel.getByLabel("Rango del asiento 1").fill("AsAh");
      await panel.getByRole("button", { name: "Aplicar cálculo" }).click();
      await expect(
        panel.getByText(/no tiene combos compatibles/),
      ).toBeVisible();
      await expect(panel.getByTestId("showdown-equity")).toHaveText("—");
    } finally {
      const capture = await (await request.get("/api/capture")).json();
      if (capture.capture_id)
        await request.post(`/api/capture/${capture.capture_id}/stop`);
    }
  });
}
