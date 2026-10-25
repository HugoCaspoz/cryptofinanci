import { expect, test } from "@playwright/test";

test("session dashboard opens the ranked decision, its frame and explanation", async ({
  page,
}, info) => {
  test.skip(!process.env.TIMELINE_E2E, "Requires isolated session fixture");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/session/scope");
    await expect(
      page.getByRole("heading", { name: "Resumen y cobertura" }),
    ).toBeVisible();
    await expect(page.getByText(/VPIP: No disponible/)).toBeVisible();
    const top = page.locator("section").filter({
      has: page.getByRole("heading", {
        name: "TOP 10 decisiones más costosas",
      }),
    });
    await expect(top.getByRole("link")).toHaveCount(1);
    await page.screenshot({
      path: info.outputPath(`session-${width}.png`),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await top.getByRole("link").click();
    await expect(page).toHaveURL(/\/hands\/hand\?decision=/);
    await expect(page.getByTestId("historical-decision")).toBeVisible();
    await expect(
      page.getByRole("img", { name: "Fotograma del turno confirmado de Hero" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Generar explicación", exact: true })
      .click();
    await expect(page.getByTestId("decision-explanation")).toContainText(
      "Explicación local",
    );
  }
  expect(errors).toEqual([]);
});

test("session summary disappears immediately when review access is revoked", async ({
  page,
}) => {
  test.skip(!process.env.TIMELINE_E2E, "Requires isolated session fixture");
  let revoke = false;
  let latestSnapshot: string | null = null;
  let subscribe: (() => void) | undefined;
  await page.routeWebSocket("**/ws/live", (socket) => {
    const server = socket.connectToServer();
    subscribe = () => {
      if (!latestSnapshot) return;
      const event = JSON.parse(latestSnapshot);
      event.sequence += 10000;
      event.payload.capture.feedback.review_blocked = true;
      event.payload.capture.revision += 1000;
      event.payload.capture.feedback.revision += 1000;
      socket.send(JSON.stringify(event));
    };
    server.onMessage((raw) => {
      const event = JSON.parse(String(raw));
      if (event.type === "capture.snapshot") latestSnapshot = String(raw);
      if (revoke && event.type === "capture.snapshot") {
        event.payload.capture.feedback.review_blocked = true;
        event.payload.capture.revision += 1000;
        event.payload.capture.feedback.revision += 1000;
      }
      socket.send(JSON.stringify(event));
    });
  });
  await page.goto("/session/scope");
  await expect(
    page.getByRole("heading", { name: "Resumen y cobertura" }),
  ).toBeVisible();
  revoke = true;
  subscribe?.();
  await expect(
    page.getByRole("heading", { name: "Resumen y cobertura" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "TOP 10 decisiones más costosas" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Resumen protegido" }),
  ).toBeVisible();
});
