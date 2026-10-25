// Native browser selection bridges the Windows desktop and a Linux backend.
// At most one encoding/upload is in flight. This does not build a frame queue.
export function sendScreen(
  stream: MediaStream,
  captureId: string,
  fps: number,
  onEnded: () => void,
  onError: (error: Error) => void,
  kind: "screen" | "camera" = "screen",
) {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.autoplay = true;
  video.setAttribute("aria-hidden", "true");
  Object.assign(video.style, {
    position: "fixed",
    width: "1px",
    height: "1px",
    opacity: "0",
    pointerEvents: "none",
  });
  document.body.appendChild(video);
  video.srcObject = stream;
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  let closed = false;
  let timer: ReturnType<typeof setTimeout>;
  const controller = new AbortController();
  const track = stream.getVideoTracks()[0];
  track.addEventListener("ended", onEnded);
  let wakeLock: WakeLockSentinel | null = null;
  if (kind === "camera" && navigator.wakeLock) {
    void navigator.wakeLock
      .request("screen")
      .then((lock) => {
        if (closed) void lock.release();
        else wakeLock = lock;
      })
      .catch(() => {});
  }

  async function tick() {
    const start = performance.now();
    try {
      if (closed) return;
      if (video.readyState >= 2 && video.videoWidth && context) {
        const ratio = Math.min(
          1,
          1920 / video.videoWidth,
          1080 / video.videoHeight,
        );
        canvas.width = Math.max(1, Math.round(video.videoWidth * ratio));
        canvas.height = Math.max(1, Math.round(video.videoHeight * ratio));
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob(resolve, "image/jpeg", 0.85),
        );
        if (closed) return;
        if (!blob) throw new Error("No se pudo leer la imagen de la fuente.");
        const response = await fetch(
          `/api/capture/${captureId}/${kind}-frame`,
          {
            method: "POST",
            body: blob,
            signal: AbortSignal.any([
              controller.signal,
              AbortSignal.timeout(8000),
            ]),
            headers: { "Content-Type": "image/jpeg" },
          },
        );
        if (!response.ok)
          throw new Error(
            "Se interrumpió el envío de imágenes. Vuelve a conectar la fuente.",
          );
      }
      if (!closed)
        timer = setTimeout(
          tick,
          Math.max(1, 1000 / fps - (performance.now() - start)),
        );
    } catch (error) {
      if (!closed)
        onError(
          error instanceof Error
            ? error
            : new Error("No se pudo enviar la imagen."),
        );
    }
  }

  void video
    .play()
    .then(tick)
    .catch(() => {
      if (!closed)
        onError(new Error("No se pudo iniciar el vídeo de la fuente."));
    });

  return () => {
    closed = true;
    clearTimeout(timer);
    controller.abort();
    track.removeEventListener("ended", onEnded);
    stream.getTracks().forEach((item) => item.stop());
    video.pause();
    video.srcObject = null;
    video.remove();
    if (wakeLock) void wakeLock.release().catch(() => {});
  };
}
