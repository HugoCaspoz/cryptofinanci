import { useEffect, useState } from "react";
import { Icon } from "../components/Icon";
import { useCapture } from "./CaptureProvider";
import { TableOverlay } from "../table/TableOverlay";
import type { LayoutEditorState } from "../table/useTableLayout";

export function Preview({ editor }: { editor: LayoutEditorState }) {
  const { capture } = useCapture();
  const [frame, setFrame] = useState<{
    url: string;
    width: number;
    height: number;
  } | null>(null);
  const [error, setError] = useState(false);
  const active =
    capture.state === "running" ||
    capture.state === "ended" ||
    capture.state === "error";

  useEffect(() => {
    let disposed = false;
    let currentUrl: string | null = null;
    let timer: ReturnType<typeof setTimeout>;
    let frameId = 0;
    const controller = new AbortController();
    setFrame(null);
    setError(false);
    async function poll() {
      try {
        const response = await fetch(
          `/api/capture/${capture.capture_id}/frame?after=${frameId}`,
          {
            signal: AbortSignal.any([
              controller.signal,
              AbortSignal.timeout(5000),
            ]),
            cache: "no-store",
          },
        );
        if (response.status === 200) {
          const blob = await response.blob();
          if (disposed) return;
          const nextUrl = URL.createObjectURL(blob);
          const previous = currentUrl;
          currentUrl = nextUrl;
          frameId = Number(response.headers.get("X-Frame-Id"));
          setFrame({
            url: nextUrl,
            width: Number(response.headers.get("X-Frame-Width")),
            height: Number(response.headers.get("X-Frame-Height")),
          });
          if (previous) URL.revokeObjectURL(previous);
        } else if (response.status !== 204)
          throw new Error("Preview unavailable");
        if (!disposed) setError(false);
      } catch {
        if (!disposed) setError(true);
      }
      if (!disposed) timer = setTimeout(poll, 1000 / capture.capture_fps);
    }
    if (capture.capture_id && active) void poll();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [capture.capture_id, capture.capture_fps, active]);

  return (
    <div className="capture-preview">
      {frame ? (
        <div className="preview-stage">
          <img src={frame.url} alt="Frame recibido por el servidor" />
          <TableOverlay
            editor={editor}
            width={frame.width}
            height={frame.height}
          />
        </div>
      ) : (
        <div className="video-empty">
          <div className="empty-icon">
            <Icon name="video" size={30} />
          </div>
          <h3>
            {capture.state === "running"
              ? "Esperando el primer frame…"
              : "Elige tu punto de vista."}
          </h3>
          <p>
            Abre un vídeo o comparte una ventana.
            <br />
            Verás aquí las imágenes recibidas por el servidor.
          </p>
        </div>
      )}
      {capture.state === "ended" && (
        <span className="preview-badge">VÍDEO FINALIZADO · ÚLTIMO FRAME</span>
      )}
      {capture.state === "error" && (
        <span className="preview-badge">CAPTURA INTERRUMPIDA</span>
      )}
      {error && (
        <span className="preview-badge" role="alert">
          Previsualización sin conexión. Reintentando…
        </span>
      )}
    </div>
  );
}
