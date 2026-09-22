// Native browser selection bridges the Windows desktop and a Linux backend.
// At most one encoding/upload is in flight. This does not build a frame queue.
export function sendScreen(
  stream: MediaStream,
  captureId: string,
  fps: number,
  onEnded: () => void,
  onError: (error: Error) => void,
) {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.srcObject = stream;
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  let closed = false;
  let timer: ReturnType<typeof setTimeout>;
  const controller = new AbortController();
  const track = stream.getVideoTracks()[0];
  track.addEventListener("ended", onEnded);

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
        if (!blob) throw new Error("No se pudo leer la pantalla compartida.");
        const response = await fetch(`/api/capture/${captureId}/screen-frame`, {
          method: "POST",
          body: blob,
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(8000),
          ]),
          headers: { "Content-Type": "image/jpeg" },
        });
        if (!response.ok)
          throw new Error(
            "Se interrumpió el envío de pantalla. Vuelve a compartirla.",
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
            : new Error("No se pudo enviar la pantalla."),
        );
    }
  }

  void video
    .play()
    .then(tick)
    .catch(() => {
      if (!closed)
        onError(new Error("No se pudo iniciar la pantalla compartida."));
    });

  return () => {
    closed = true;
    clearTimeout(timer);
    controller.abort();
    track.removeEventListener("ended", onEnded);
    stream.getTracks().forEach((item) => item.stop());
    video.pause();
    video.srcObject = null;
  };
}
