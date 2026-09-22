import { expect, test } from "@playwright/test";

test("layout loading failure can be retried without breaking capture controls", async ({
  page,
}) => {
  await page.route("**/api/table-layout", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Layout no disponible" }),
    }),
  );
  await page.goto("/live");
  const layoutPanel = page.getByRole("region", {
    name: "Configuración de la mesa",
  });
  await expect(layoutPanel.getByRole("alert")).toContainText(
    "Layout no disponible",
  );
  await expect(
    page.getByLabel("Mostrar regiones", { exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Compartir pantalla o ventana" }),
  ).toBeVisible();
  await page.unroute("**/api/table-layout");
  await page.getByRole("button", { name: "Recargar layout" }).click();
  await expect(
    page.getByLabel("Mostrar regiones", { exact: true }),
  ).toBeEnabled();
  await expect(layoutPanel.getByRole("alert")).toHaveCount(0);
});

test("real backend handshake, ping and navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Todo empieza en la mesa." }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Backend conectado");
  await expect(
    page.getByText("Respuesta de conexión recibida").first(),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("dashboard.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Abrir panel en directo" }).click();
  await expect(page).toHaveURL(/\/live$/);
  const repliesBefore = await page
    .getByText("Respuesta de conexión recibida")
    .count();
  await page.getByRole("button", { name: "Comprobar conexión" }).click();
  await expect
    .poll(() => page.getByText("Respuesta de conexión recibida").count())
    .toBeGreaterThan(repliesBefore);
  await page.screenshot({
    path: test.info().outputPath("live.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Sesiones", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Tu historia todavía está por escribir.",
    }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("session deep link and unknown route survive refresh", async ({
  page,
}) => {
  await page.goto("/session/does-not-exist");
  await expect(
    page.getByRole("heading", { name: "Sesión no encontrada" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Sesión no encontrada" }),
  ).toBeVisible();
  await page.goto("/unknown");
  await expect(
    page.getByRole("heading", { name: "Esta página no está en la mesa." }),
  ).toBeVisible();
});

test("sessions distinguish server failure from empty data and can retry", async ({
  page,
}) => {
  await page.route("**/api/sessions", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/sessions");
  await expect(page.getByRole("alert")).toContainText(
    "No se pudieron cargar las sesiones.",
  );
  await page.unroute("**/api/sessions");
  await page.getByRole("button", { name: "Reintentar" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Tu historia todavía está por escribir.",
    }),
  ).toBeVisible();
});

test("mobile navigation has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of [
    "/",
    "/live",
    "/hands",
    "/sessions",
    "/session/missing",
  ]) {
    await page.goto(path);
    await expect(page.getByRole("navigation")).toBeVisible();
    const fits = await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    );
    expect(fits).toBeTruthy();
    if (path === "/") {
      await expect(page.getByRole("status")).toHaveText("Backend conectado");
      await page.screenshot({
        path: test.info().outputPath("mobile.png"),
        fullPage: true,
      });
    }
  }
});

test("websocket reconnects after a transport interruption", async ({
  page,
}) => {
  let connections = 0;
  await page.routeWebSocket("**/ws/live", (ws) => {
    connections += 1;
    const server = ws.connectToServer();
    if (connections === 1)
      server.onMessage((message) => {
        ws.send(message);
        if (String(message).includes("system.ready"))
          setTimeout(() => ws.close(), 300);
      });
  });
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Reconectando…");
  await expect(page.getByRole("status")).toHaveText("Backend conectado");
  expect(connections).toBeGreaterThanOrEqual(2);
  await expect(
    page.getByText("Respuesta de conexión recibida").first(),
  ).toBeVisible();
});
