import { expect, test } from "@playwright/test";

test("decision timeline restores its frame and frozen state on desktop and mobile", async ({
  page,
}, info) => {
  test.skip(
    !process.env.TIMELINE_E2E,
    "Requires the isolated timeline fixture backend",
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/hands/hand");
    const review = page.getByRole("region", { name: "Revisión de la mano" });
    await expect(
      review.getByRole("heading", { name: "Línea temporal de decisiones" }),
    ).toBeVisible();
    await review.getByRole("button", { name: /Revisar flop/ }).click();
    const image = review.getByRole("img", {
      name: "Fotograma del turno confirmado de Hero",
    });
    await expect(image).toBeVisible();
    await expect
      .poll(() =>
        image.evaluate((element) => (element as HTMLImageElement).naturalWidth),
      )
      .toBe(640);
    await review
      .getByText("Estado de juego congelado", { exact: true })
      .click();
    await expect(
      review.getByRole("columnheader", { name: "Stack", exact: true }),
    ).toBeVisible();
    await expect(review.getByTestId("historical-decision")).toContainText(
      "Hero:",
    );
    const explanation = review.getByRole("region", {
      name: "Explicación de la decisión",
    });
    await explanation
      .getByRole("button", { name: "Generar explicación", exact: true })
      .click();
    await expect(explanation.getByTestId("decision-explanation")).toContainText(
      "Explicación local",
    );
    await expect(explanation.getByTestId("decision-explanation")).toContainText(
      "no es dinero perdido",
    );
    await explanation
      .getByLabel("Detalle de la explicación")
      .selectOption("advanced");
    await expect(explanation.getByTestId("decision-explanation")).toHaveCount(
      0,
    );
    await explanation
      .getByRole("button", { name: "Generar explicación", exact: true })
      .click();
    await expect(explanation.getByTestId("decision-explanation")).toContainText(
      "Rangos adaptativos congelados",
    );
    await page.screenshot({
      path: info.outputPath(`timeline-${width}.png`),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  expect(errors).toEqual([]);
});
