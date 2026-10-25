import { openLiveTools } from "../tests/openLiveTools";
import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test("strategy and bluff analysis show only while Hero decides and archive the decision", async ({
  page,
  request,
}, info) => {
  test.setTimeout(110000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/live");
  await openLiveTools(page);
  const opponents = page.getByRole("region", { name: "Modelo de rivales" });
  const strategy = page.getByRole("region", { name: "Motor de estrategia" });
  await expect(strategy).toContainText("Entrenamiento");
  await page
    .getByLabel("Archivo de vídeo")
    .setInputFiles(resolve("../sample_data/opponents-demo.avi"));
  await page.getByRole("button", { name: "Reproducir archivo" }).click();
  try {
    await expect(page.getByTestId("current-pot")).toHaveText("150", {
      timeout: 12000,
    });
    const identity = (await (await request.get("/api/capture")).json())
      .capture_id;
    await expect
      .poll(async () => {
        const frames = await (
          await request.get(`/api/capture/${identity}/important-frames`)
        ).json();
        return frames.items.some(
          (frame: { kind: string }) => frame.kind === "hand_started",
        );
      })
      .toBe(true);
    for (const seat of [3, 4, 5, 6])
      await opponents.getByLabel(`Estadísticas asiento ${seat}`).uncheck();
    await opponents.getByLabel("Botón para estadísticas").selectOption("1");
    await opponents
      .getByLabel("Confirmo participantes e inicio sin acciones previas")
      .check();
    await opponents
      .getByRole("button", { name: "Confirmar inicio para estadísticas" })
      .click();
    await expect(opponents.getByRole("status")).toContainText(
      "Inicio confirmado",
    );
    const poker = page.getByRole("region", { name: "Motor matemático" });
    await poker.getByLabel("Hero para cálculos").selectOption("1");
    await poker.getByLabel("Incluir asiento 2").check();
    await poker.getByLabel("Bote observado").selectOption("true");
    await poker.getByRole("button", { name: "Aplicar cálculo" }).click();
    // Hero's first preflop turn needs the preflop table context, not configured here.
    await expect(strategy.getByTestId("strategy-reason")).toContainText(
      "Estrategia preflop",
      { timeout: 25000 },
    );
    const baseline = strategy.getByTestId("strategy-baseline");
    await expect(baseline).toBeVisible({ timeout: 45000 });
    for (const label of ["Fold", "Call", "Raise a 9.0 BB"])
      await expect(baseline).toContainText(label);
    await expect(strategy.getByTestId("strategy-exploit")).toContainText(
      "Call",
    );
    await expect(strategy).toContainText("a igualar 3.0 BB");
    await expect(strategy).toContainText("en posición");
    await expect(strategy).toContainText("Rango del rival");
    const bluff = strategy.getByTestId("bluff-analysis");
    for (const label of ["Fold necesario", "Valor de showdown", "Bloqueadores"])
      await expect(bluff).toContainText(label);
    await expect(strategy.getByTestId("bluff-verdict")).toHaveText(
      /Sin farol recomendado|Candidato a|Apuesta de valor/,
    );
    const current = await (await request.get("/api/strategy")).json();
    expect(current.result.street).toBe("flop");
    const snapshotId = current.result.decision_snapshot_id;
    expect(snapshotId).toMatch(/^[a-f0-9]{64}$/);
    const frozen = await (
      await request.get(`/api/decisions/${snapshotId}`)
    ).json();
    expect(frozen.request.state.hero_cards).toEqual(["As", "Kh"]);
    expect(frozen.request.state.board).toEqual(["Js", "7c", "4d"]);
    expect(frozen.history_complete).toBe(true);
    expect(frozen.strategy_input_available).toBe(true);
    expect(frozen.request.decision.pending).toEqual([1]);
    expect(frozen.request.decision.exploit_pools[0][1].length).toBeGreaterThan(
      100,
    );
    expect(
      frozen.actions.every(
        (a: { sequence: number; timestamp: number }) =>
          a.sequence <= frozen.source_event_sequence &&
          a.timestamp <= frozen.timestamp,
      ),
    ).toBe(true);
    expect(
      frozen.actions.some((a: { type: string }) => a.type === "PLAYER_FOLDED"),
    ).toBe(false);
    const explanation = strategy.getByRole("region", {
      name: "Explicación de la decisión",
    });
    await explanation
      .getByRole("button", { name: "Generar explicación", exact: true })
      .click();
    await expect(explanation.getByTestId("decision-explanation")).toContainText(
      "Explicación local",
    );
    await expect(explanation.getByTestId("decision-explanation")).toContainText(
      "Baseline",
    );
    const telemetry = (await (await request.get("/api/capture")).json())
      .pipeline.latencies;
    expect(telemetry.strategy.samples).toBeGreaterThan(0);
    expect(telemetry.equity.samples).toBeGreaterThan(0);
    expect(telemetry.strategy_total.frame_id).toBe(current.result.frame_id);
    await info.attach("latency-metrics", {
      body: JSON.stringify(telemetry, null, 2),
      contentType: "application/json",
    });
    const summary = current.result.baseline_strategy.summary;
    expect(
      Object.values(summary).reduce((a, b) => (a as number) + (b as number), 0),
    ).toBeCloseTo(1, 6);
    await strategy.screenshot({
      path: info.outputPath("strategy-desktop.png"),
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await strategy
      .getByTestId("strategy-result")
      .screenshot({ path: info.outputPath("strategy-mobile.png") });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.setViewportSize({ width: 1440, height: 1000 });
    // The live strategy clears after Hero folds; the earlier snapshot remains unchanged.
    await expect(strategy.getByTestId("strategy-result")).toHaveCount(0, {
      timeout: 15000,
    });
    expect(
      await (await request.get(`/api/decisions/${snapshotId}`)).json(),
    ).toEqual(frozen);
    const decisions = page.getByRole("region", { name: "Decisiones de Hero" });
    await decisions
      .getByRole("button", { name: /Ver decisión · flop/ })
      .click();
    const detail = decisions.getByTestId("decision-detail");
    await expect(detail).toContainText("Hero: As Kh · Board: Js 7c 4d");
    await expect(detail).toContainText("Historial observado desde el inicio");
    const evaluation = detail.getByTestId("decision-evaluation");
    await expect(evaluation).toContainText("Acción de Hero: Fold", {
      timeout: 15000,
    });
    await expect(evaluation).toHaveCount(1);
    await expect(
      detail.getByRole("region", { name: "Explicación de la decisión" }),
    ).toHaveCount(1);
    await expect(evaluation).toContainText("Diferencia de EV:");
    await expect(evaluation).toContainText("Confianza limitada");
    const comparison = await (
      await request.get(`/api/decisions/${snapshotId}/evaluation`)
    ).json();
    expect(comparison.status).toBe("complete");
    expect(comparison.result.status).toBe("ready");
    expect(comparison.result.actual_action.action).toBe("FOLD");
    expect(comparison.result.baseline.actual_ev_bb).toBe(0);
    expect(comparison.result.baseline.ev_difference_bb).toBeCloseTo(
      -current.result.baseline_strategy.highest_ev.ev_bb,
      8,
    );
    expect(comparison.result.exploitative.ev_difference_bb).toBeCloseTo(
      -current.result.exploitative_strategy.highest_ev.ev_bb,
      8,
    );
    expect(comparison.result.source_event_sequence).toBe(
      frozen.source_event_sequence,
    );
    expect(comparison.result.strategy_result.timestamp).toBe(frozen.timestamp);
    expect(comparison.result.confidence.value).toBeNull();
    await page.reload();
    await openLiveTools(page);
    await decisions
      .getByRole("button", { name: /Ver decisión · flop/ })
      .click();
    await expect(evaluation).toContainText("Acción de Hero: Fold");
    await detail
      .getByText("Rangos y estadísticas utilizados", { exact: true })
      .click();
    await expect(detail).toContainText("combos ponderados guardados");
    await decisions.screenshot({
      path: info.outputPath("decisions-desktop.png"),
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await decisions.screenshot({
      path: info.outputPath("decisions-mobile.png"),
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    const firstPage = await (
      await request.get(
        `/api/decisions?hand_id=${encodeURIComponent(current.result.hand_id)}&limit=1`,
      )
    ).json();
    expect(firstPage.items).toHaveLength(1);
    expect(firstPage.has_more).toBe(true);
    const rest = await (
      await request.get(
        `/api/decisions?hand_id=${encodeURIComponent(current.result.hand_id)}&after=${firstPage.next_after}`,
      )
    ).json();
    const ids = [...firstPage.items, ...rest.items].map(
      (item: { id: string }) => item.id,
    );
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain(snapshotId);
    const archive = await (
      await request.get(
        `/api/strategy/archive?hand_id=${encodeURIComponent(current.result.hand_id)}`,
      )
    ).json();
    const flop = archive.items.filter(
      (item: { result: { street: string } }) => item.result.street === "flop",
    );
    expect(flop.length).toBeGreaterThan(0);
    expect(flop[0].mode).toBe("TRAINING");
    expect(flop[0].input.decision.pending).toEqual([1]);
    expect(flop[0].input.decision_snapshot_id).toBe(snapshotId);
    expect(flop[0].result.exploitative_strategy.options.length).toBe(3);
    expect(flop[0].result.bluff.version).toBe("bluff-analyzer-v1");
    expect(
      flop[0].result.bluff.exploit_strategy.recommended_sizing.action,
    ).toBe("RAISE");
    expect(errors).toEqual([]);
  } finally {
    const capture = await (await request.get("/api/capture")).json();
    if (capture.capture_id)
      await request.post(`/api/capture/${capture.capture_id}/stop`);
  }
});
