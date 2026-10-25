import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test("Railway serves the protected app over trusted HTTPS with PostgreSQL and WebSocket", async ({
  browser,
  request,
}) => {
  test.skip(!process.env.RAILWAY_E2E_URL, "Requires deployed Railway instance");
  const origin = process.env.RAILWAY_E2E_URL!;
  const password = readFileSync(
    "../.railway-local/password.txt",
    "utf8",
  ).trim();
  const health = await request.get(`${origin}/health`);
  expect(health.ok()).toBe(true);
  expect(await health.json()).toMatchObject({
    status: "ok",
    phase: 30,
    mode: "LIVE_REAL_MONEY",
    persistence: "postgresql",
  });
  expect((await request.get(`${origin}/api/capture`)).status()).toBe(401);
  expect((await request.get(`${origin}/`)).url()).toBe(`${origin}/login`);
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  try {
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${origin}/live`);
    await page.getByLabel("Usuario", { exact: true }).fill("zeros");
    await page.getByLabel("Contraseña", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Entrar", exact: true }).click();
    await expect(page.getByRole("banner").getByRole("status")).toHaveText(
      "Backend conectado",
    );
    await expect(
      page.getByRole("button", { name: "Usar cámara", exact: true }),
    ).toBeEnabled();
    expect(
      await page.evaluate(
        () =>
          isSecureContext &&
          typeof navigator.mediaDevices?.getUserMedia === "function",
      ),
    ).toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByRole("link", { name: "Sesiones", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Tus sesiones", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Consultando sesiones…")).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(errors).toEqual([]);
    await page.getByRole("button", { name: "Salir", exact: true }).click();
    await expect(page).toHaveURL(`${origin}/login`);
    expect((await context.request.get(`${origin}/api/capture`)).status()).toBe(
      401,
    );
  } finally {
    await context.close();
  }
});
