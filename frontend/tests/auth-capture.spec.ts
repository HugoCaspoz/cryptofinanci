import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test.use({
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
  permissions: ["camera"],
});
test("authenticated camera sends frames through the production nginx session gate", async ({
  page,
  context,
}) => {
  test.skip(
    !process.env.AUTH_CAPTURE_E2E_URL,
    "Requires isolated authenticated nginx backend",
  );
  const origin = process.env.AUTH_CAPTURE_E2E_URL!;
  await page.goto(`${origin}/live`);
  await page.getByLabel("Usuario", { exact: true }).fill("zeros");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill(readFileSync("../.railway-local/password.txt", "utf8").trim());
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Usar cámara", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Usar cámara", exact: true }).click();
  let identity = "";
  try {
    await expect
      .poll(
        async () => {
          const status = await (
            await context.request.get(`${origin}/api/capture`)
          ).json();
          identity = status.capture_id;
          return status.source === "camera" && status.frame?.frame_id >= 3;
        },
        { timeout: 12000 },
      )
      .toBe(true);
    await page
      .getByRole("button", { name: "Detener captura", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await (await context.request.get(`${origin}/api/capture`)).json())
            .state,
      )
      .toBe("stopped");
  } finally {
    if (identity)
      await context.request.post(`${origin}/api/capture/${identity}/stop`);
  }
});
