import { expect, test } from "@playwright/test";

test("mobile live view starts compact and exposes setup on demand", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/live");
  await expect(
    page.getByRole("heading", { name: "Preparar la captura", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollHeight),
  ).toBeLessThan(6000);
  await expect(
    page.getByRole("region", { name: "Motor matemático" }),
  ).toBeHidden();
  await page
    .getByRole("button", {
      name: "Configurar Hero y participantes",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("region", { name: "Motor matemático" }),
  ).toBeVisible();
});

test("calibration fits camera dimensions and makes restart explicit", async ({
  page,
  request,
}) => {
  test.skip(!process.env.CAMERA_E2E, "Requires isolated backend");
  const original = await request.get("/api/table-layout");
  const layout = await original.json();
  await page.goto("/live");
  const started = await request.post("/api/capture/screen", { data: {} });
  const id = (await started.json()).capture_id;
  try {
    const encoded = await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 720;
      return canvas.toDataURL("image/jpeg").split(",")[1];
    });
    await request.post(`/api/capture/${id}/screen-frame`, {
      data: Buffer.from(encoded, "base64"),
    });
    await page
      .getByRole("button", {
        name: "Preparar mesa y reconocimiento",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", {
        name: "Adaptar regiones a la imagen",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", { name: "Guardar layout", exact: true })
      .click();
    await expect(
      page.getByText("El detector sigue usando la calibración anterior."),
    ).toBeVisible();
    const saved = await (await request.get("/api/table-layout")).json();
    expect([saved.width, saved.height]).toEqual([1280, 720]);
    await page
      .getByRole("button", {
        name: "Detener para aplicar la calibración",
        exact: true,
      })
      .click();
    await expect
      .poll(
        async () => (await (await request.get("/api/capture")).json()).state,
      )
      .toBe("stopped");
  } finally {
    await request.post(`/api/capture/${id}/stop`);
    const latest = await request.get("/api/table-layout");
    await request.put("/api/table-layout", {
      data: layout,
      headers: { "If-Match": latest.headers()["etag"] },
    });
  }
});
