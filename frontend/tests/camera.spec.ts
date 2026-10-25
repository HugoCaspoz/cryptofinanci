import { expect, test } from "@playwright/test";

test.use({
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
  permissions: ["camera"],
});

test.beforeEach(async ({ page }) => {
  test.skip(!process.env.CAMERA_E2E, "Requires an isolated camera backend");
  await page.addInitScript(() => {
    const acquire = navigator.mediaDevices.getUserMedia.bind(
      navigator.mediaDevices,
    );
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await acquire(constraints);
      Object.assign(window, {
        cameraTestStream: stream,
        cameraTestConstraints: constraints,
      });
      return stream;
    };
  });
});

test("camera uploads real encoded browser frames and releases tracks on remote stop", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/live");
  await expect(
    page.getByRole("button", { name: "Usar cámara", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Cámara", { exact: true }).selectOption("user");
  await page.getByRole("button", { name: "Usar cámara", exact: true }).click();
  let identity = "";
  try {
    await expect
      .poll(async () => {
        const data = await (await request.get("/api/capture")).json();
        identity = data.capture_id;
        return data.source === "camera" && data.frame?.frame_id > 1;
      })
      .toBe(true);
    expect(
      await page.evaluate(() => {
        const data = window as unknown as {
          cameraTestStream: MediaStream;
          cameraTestConstraints: MediaStreamConstraints;
        };
        return {
          audio: data.cameraTestConstraints.audio,
          tracks: data.cameraTestStream.getAudioTracks().length,
          facing: (data.cameraTestConstraints.video as MediaTrackConstraints)
            .facingMode,
        };
      }),
    ).toEqual({ audio: false, tracks: 0, facing: { ideal: "user" } });
    expect(
      (await request.get(`/api/capture/${identity}/frame`)).headers()[
        "content-type"
      ],
    ).toBe("image/jpeg");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByRole("link", { name: "Resumen", exact: true }).click();
    await expect
      .poll(
        async () => (await (await request.get("/api/capture")).json()).state,
      )
      .toBe("running");
    expect((await request.post(`/api/capture/${identity}/stop`)).ok()).toBe(
      true,
    );
    await expect
      .poll(() =>
        page.evaluate(() => {
          const stream = (
            window as unknown as { cameraTestStream: MediaStream }
          ).cameraTestStream;
          return stream
            .getTracks()
            .every((track) => track.readyState === "ended");
        }),
      )
      .toBe(true);
  } finally {
    if (identity) await request.post(`/api/capture/${identity}/stop`);
  }
});

test("camera permission denial never starts a backend capture", async ({
  page,
}) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException("denied", "NotAllowedError");
    };
  });
  let starts = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/capture/camera")) starts++;
  });
  await page.goto("/live");
  await page.getByRole("button", { name: "Usar cámara", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Permiso de cámara denegado" }),
  ).toBeVisible();
  expect(starts).toBe(0);
});

test("server rejection releases camera acquired before the request", async ({
  page,
}) => {
  await page.route("**/api/capture/camera", (route) =>
    route.fulfill({ status: 409, json: { detail: "Otra fuente está activa" } }),
  );
  await page.goto("/live");
  await page.getByRole("button", { name: "Usar cámara", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Otra fuente está activa" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      (window as unknown as { cameraTestStream: MediaStream }).cameraTestStream
        .getTracks()
        .every((t) => t.readyState === "ended"),
    ),
  ).toBe(true);
});

test("hiding the mobile tab stops capture and camera", async ({
  page,
  request,
}) => {
  await page.goto("/live");
  await page.getByRole("button", { name: "Usar cámara", exact: true }).click();
  let identity = "";
  try {
    await expect
      .poll(async () => {
        const data = await (await request.get("/api/capture")).json();
        identity = data.capture_id;
        return data.source === "camera" && data.frame != null;
      })
      .toBe(true);
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "hidden",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect
      .poll(
        async () => (await (await request.get("/api/capture")).json()).state,
      )
      .toBe("stopped");
    await expect(
      page.getByRole("alert").filter({ hasText: "ocultar la pestaña" }),
    ).toBeVisible();
    expect(
      await page.evaluate(() =>
        (
          window as unknown as { cameraTestStream: MediaStream }
        ).cameraTestStream
          .getTracks()
          .every((t) => t.readyState === "ended"),
      ),
    ).toBe(true);
  } finally {
    if (identity) await request.post(`/api/capture/${identity}/stop`);
  }
});
