import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import https from "node:https";

test("LAN HTTPS verifies with its CA, requires credentials and supports WebSocket", async ({
  browser,
}) => {
  test.skip(!process.env.MOBILE_E2E_URL, "Requires optional LAN gateway");
  const url = process.env.MOBILE_E2E_URL!;
  const password = readFileSync("../.mobile/password.txt", "utf8").trim();
  const ca = readFileSync("../.mobile/zeros-root.crt");
  const get = (path: string, authenticate: boolean) =>
    new Promise<number | undefined>((resolve, reject) => {
      const request = https.get(
        `${url}${path}`,
        {
          ca,
          headers: authenticate
            ? {
                Authorization: `Basic ${Buffer.from(`zeros:${password}`).toString("base64")}`,
              }
            : {},
        },
        (response) => {
          response.resume();
          resolve(response.statusCode);
        },
      );
      request.on("error", reject);
    });
  expect(await get("/health", false)).toBe(401);
  expect(await get("/health", true)).toBe(200);
  // TLS chain is checked above with the exported CA; browser bypass is test-only.
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    httpCredentials: { username: "zeros", password },
  });
  try {
    const page = await context.newPage();
    await page.goto(`${url}/live`);
    await expect(page.getByRole("banner").getByRole("status")).toHaveText(
      "Backend conectado",
    );
    await expect(
      page.getByRole("button", { name: "Usar cámara", exact: true }),
    ).toBeEnabled();
    expect(await page.evaluate(() => isSecureContext)).toBe(true);
  } finally {
    await context.close();
  }
});
