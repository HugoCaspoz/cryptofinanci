import { openLiveTools } from "../tests/openLiveTools";
import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

for (const policy of ["SESSION_FINISHED", "HAND_FINISHED"]) {
  test(`real-money review follows ${policy} and hides again on a new capture`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(115000);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/live");
    await openLiveTools(page);
    await page.getByLabel("Momento de revisión").selectOption(policy);
    await page
      .getByRole("button", { name: "Guardar política de revisión" })
      .click();
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/capture")).json()).feedback
            .next_release,
      )
      .toBe(policy);
    await page
      .getByLabel("Archivo de vídeo")
      .setInputFiles(resolve("../sample_data/opponents-demo.avi"));
    await page.getByRole("button", { name: "Reproducir archivo" }).click();
    try {
      await expect(page.getByTestId("current-pot")).toHaveText("150", {
        timeout: 12000,
      });
      const opponents = page.getByRole("region", { name: "Modelo de rivales" });
      for (const seat of [3, 4, 5, 6])
        await opponents.getByLabel(`Estadísticas asiento ${seat}`).uncheck();
      await opponents.getByLabel("Botón para estadísticas").selectOption("1");
      await opponents
        .getByLabel("Confirmo participantes e inicio sin acciones previas")
        .check();
      const confirmed = page.waitForResponse(
        (r) =>
          r.url().endsWith("/api/opponents/context") &&
          r.request().method() === "PUT",
      );
      await opponents
        .getByRole("button", { name: "Confirmar inicio para estadísticas" })
        .click();
      expect((await confirmed).status()).toBe(200);
      const poker = page.getByRole("region", { name: "Motor matemático" });
      await poker.getByLabel("Hero para cálculos").selectOption("1");
      await poker.getByLabel("Incluir asiento 2").check();
      await poker.getByLabel("Bote observado").selectOption("true");
      await poker.getByRole("button", { name: "Aplicar cálculo" }).click();
      const initial = await (await request.get("/api/capture")).json();
      const handId = initial.observation_state.game_state.hand_id;
      expect(initial.strategy.result).toBeNull();
      expect(initial.opponents.analysis).toBeNull();
      expect(initial.opponents.observations.profiles.length).toBeGreaterThan(0);
      expect(
        (await request.get(`/api/decisions?hand_id=${handId}`)).status(),
      ).toBe(403);
      await page.goto(`/hands/${handId}`);
      const review = page.getByRole("region", { name: "Revisión de la mano" });
      await expect(review).toContainText("Revisión oculta");
      await expect(review.getByTestId("historical-decision")).toHaveCount(0);
      // The whole video runs once; EOF alone must not act as SESSION_FINISHED.
      await expect
        .poll(
          async () => (await (await request.get("/api/capture")).json()).state,
          { timeout: 80000, intervals: [1000] },
        )
        .toBe("ended");
      const access = await (
        await request.get(`/api/feedback/hands/${handId}`)
      ).json();
      expect(access.session.release_policy).toBe(policy);
      expect(access.allowed).toBe(policy === "HAND_FINISHED");
      await expect(
        page.getByRole("heading", { name: "Mano 1 · Terminada", exact: true }),
      ).toBeVisible();
      if (policy === "SESSION_FINISHED") {
        expect(
          (
            await request.get(`/api/strategy/archive?hand_id=${handId}`)
          ).status(),
        ).toBe(403);
        await review
          .getByLabel("He terminado la sesión de juego de esta captura")
          .check();
        await review
          .getByRole("button", { name: "Finalizar sesión y abrir revisión" })
          .click();
      }
      const archive = await (
        await request.get(`/api/decisions?hand_id=${handId}`)
      ).json();
      const flop = archive.items.find(
        (d: { street: string }) => d.street === "flop",
      );
      expect(
        flop,
        "El OCR debe conservar el turno del flop de esta demo",
      ).toBeDefined();
      const identity = flop.id;
      const evaluated = await request.get(
        `/api/decisions/${identity}/evaluation`,
      );
      expect(evaluated.status()).toBe(200);
      const comparison = await evaluated.json();
      expect(
        comparison.result?.status,
        comparison.result?.reason ?? "Evaluación pendiente",
      ).toBe("ready");
      await review.getByRole("button", { name: /Revisar flop/ }).click();
      await expect(review.getByTestId("decision-evaluation")).toContainText(
        "Acción de Hero: Fold",
      );
      await review
        .getByText("Alternativas y análisis de farol", { exact: true })
        .click();
      await expect(review.getByTestId("review-baseline")).toContainText("Call");
      await expect(review.getByTestId("bluff-analysis")).toBeVisible();
      const explanation = review.getByRole("region", {
        name: "Explicación de la decisión",
      });
      await explanation
        .getByRole("button", { name: "Generar explicación", exact: true })
        .click();
      await expect(
        explanation.getByTestId("decision-explanation"),
      ).toContainText("no es dinero perdido");
      await explanation
        .getByLabel("Detalle de la explicación")
        .selectOption("advanced");
      await explanation
        .getByRole("button", { name: "Generar explicación", exact: true })
        .click();
      await expect(
        explanation.getByTestId("decision-explanation"),
      ).toContainText("Rangos adaptativos congelados");
      await expect(
        review.getByRole("img", {
          name: "Fotograma del turno confirmado de Hero",
        }),
      ).toBeVisible();
      await review.screenshot({ path: info.outputPath("review-desktop.png") });
      await page.setViewportSize({ width: 390, height: 844 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
      await review.screenshot({ path: info.outputPath("review-mobile.png") });
      await page.reload();
      await review.getByRole("button", { name: /Revisar flop/ }).click();
      await expect(review.getByTestId("decision-evaluation")).toContainText(
        "Acción de Hero: Fold",
      );
      // Start a new source from another client while the archived analysis is open.
      const next = await request.post("/api/capture/screen", {
        data: { name: "Review revocation check", capture_fps: 1 },
      });
      expect(next.status()).toBe(201);
      await expect(review.getByTestId("historical-decision")).toHaveCount(0);
      expect((await request.get(`/api/decisions/${identity}`)).status()).toBe(
        403,
      );
      expect(
        (await request.get(`/api/decisions/${identity}/evaluation`)).status(),
      ).toBe(403);
      expect(
        (await request.get(`/api/strategy/archive?hand_id=${handId}`)).status(),
      ).toBe(403);
      expect(
        (
          await request.post(`/api/decisions/${identity}/explanation`, {
            data: { style: "simple" },
          })
        ).status(),
      ).toBe(403);
      await expect(review.getByTestId("decision-explanation")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      const capture = await (await request.get("/api/capture")).json();
      if (capture.capture_id)
        await request.post(`/api/capture/${capture.capture_id}/stop`);
      await request.put("/api/feedback/config", {
        data: { release: "SESSION_FINISHED" },
      });
    }
  });
}
