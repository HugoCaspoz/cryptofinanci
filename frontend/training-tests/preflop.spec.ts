import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test.describe.configure({ mode: "serial" });

for (const mobile of [false, true]) {
  test(`preflop confirms context, applies custom ranges and clears after acting (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(45000);
    await page.setViewportSize(
      mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
    );
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/live");
    await page
      .getByLabel("Archivo de vídeo")
      .setInputFiles(resolve("../sample_data/preflop-demo.avi"));
    await page.getByRole("button", { name: "Reproducir archivo" }).click();
    try {
      await expect(page.getByTestId("current-pot")).toHaveText("150", {
        timeout: 12000,
      });
      const panel = page.getByRole("region", { name: "Estrategia preflop" });
      await panel.getByLabel("Hero preflop").selectOption("3");
      await panel.getByLabel("Botón de esta mano").selectOption("6");
      await expect(
        panel.getByRole("button", { name: "Aplicar contexto preflop" }),
      ).toBeDisabled();
      await panel
        .getByText("Editar rangos y condiciones de la tabla", { exact: true })
        .click();
      const table = panel.getByLabel("Tabla preflop (JSON)");
      const rules = JSON.parse(await table.inputValue());
      rules[0].open_to_bb = 3;
      await table.fill(JSON.stringify(rules));
      await panel
        .getByText("Editar rangos y condiciones de la tabla", { exact: true })
        .click();
      await panel.getByLabel(/He confirmado los asientos/).check();
      await panel
        .getByRole("button", { name: "Aplicar contexto preflop" })
        .click();
      await expect(panel.getByTestId("preflop-action")).toHaveText("Raise", {
        timeout: 8000,
      });
      await expect(panel.getByTestId("preflop-sizing")).toContainText(
        "Hasta 3.00 BB en total",
      );
      await panel.screenshot({ path: info.outputPath("preflop.png") });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
      const payload = await (await request.get("/api/preflop")).json();
      expect(payload.result.confidence).toBeNull();
      expect(payload.result.context.position).toBe("UTG");
      // The real visual RAISE label removes Hero's turn at t=20 and records the action.
      await expect(page.getByTestId("current-pot")).toHaveText("450", {
        timeout: 25000,
      });
      await expect(panel.getByTestId("preflop-action")).toHaveCount(0);
      await expect(
        panel.getByText(/turno de Hero|primera decisión/),
      ).toBeVisible();
      expect(errors).toEqual([]);
    } finally {
      const current = await (await request.get("/api/capture")).json();
      if (current.capture_id)
        await request.post(`/api/capture/${current.capture_id}/stop`);
    }
  });
}
