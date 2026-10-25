import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { LatencyWindow } from "../live/latency";
import type { LatencySummary } from "../live/latency";
import type { ReactNode } from "react";
import { emptyCapture, readResponse } from "./types";
import type { CaptureStatus } from "./types";
import { sendScreen } from "./screenSender";
import { useLive } from "../live/LiveProvider";

type CaptureContextValue = {
  capture: CaptureStatus;
  busy: boolean;
  error: string | null;
  available: boolean;
  uiLatency: LatencySummary | null;
  startFile: (file: File, fps: number) => Promise<void>;
  startScreen: (fps: number) => Promise<void>;
  startCamera: (fps: number, facing: "environment" | "user") => Promise<void>;
  stop: () => Promise<void>;
};

const CaptureContext = createContext<CaptureContextValue | null>(null);

export function CaptureProvider({ children }: { children: ReactNode }) {
  const [delivery, setDelivery] = useState<{
    capture: CaptureStatus;
    receivedAt: number | null;
  }>({ capture: emptyCapture, receivedAt: null });
  const capture = delivery.capture;
  const [uiSample, setUiSample] = useState<{
    owner: string;
    value: LatencySummary;
  } | null>(null);
  const uiWindow = useRef<{ owner: string; window: LatencyWindow } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { captureSnapshot, captureReady, captureReceivedAt, status } =
    useLive();
  const available = captureReady && status === "connected";
  const localScreen = useRef<{
    id: string;
    kind: "screen" | "camera";
    cleanup: () => void;
  } | null>(null);
  const mounted = useRef(true);
  function applyCapture(
    next: CaptureStatus,
    fromStream = false,
    receivedAt: number | null = null,
  ) {
    setDelivery((current) => {
      if (next.server_id !== current.capture.server_id) {
        return fromStream || !current.capture.server_id
          ? { capture: next, receivedAt }
          : current;
      }
      return next.revision >= current.capture.revision
        ? { capture: next, receivedAt }
        : current;
    });
  }

  useEffect(() => {
    if (captureSnapshot) applyCapture(captureSnapshot, true, captureReceivedAt);
  }, [captureSnapshot, captureReceivedAt]);

  const owner = JSON.stringify([capture.server_id, capture.capture_id]);
  const uiLatency =
    available && uiSample?.owner === owner ? uiSample.value : null;
  useLayoutEffect(() => {
    if (!available) {
      uiWindow.current = null;
      setUiSample(null);
      return;
    }
    if (uiWindow.current?.owner !== owner) {
      uiWindow.current = { owner, window: new LatencyWindow() };
    }
    if (delivery.receivedAt == null || document.visibilityState !== "visible")
      return;
    let second = 0;
    let interrupted = false;
    const onVisibility = () => {
      if (document.visibilityState !== "visible") interrupted = true;
    };
    document.addEventListener("visibilitychange", onVisibility);
    // Two animation frames approximate a completed paint, without mixing server clocks.
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        if (
          interrupted ||
          document.visibilityState !== "visible" ||
          uiWindow.current?.owner !== owner
        )
          return;
        const value = uiWindow.current.window.add(
          performance.now() - delivery.receivedAt!,
          capture.frame?.frame_id ?? null,
        );
        if (value) setUiSample({ owner, value });
      });
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [
    capture.server_id,
    capture.capture_id,
    capture.revision,
    delivery.receivedAt,
    available,
    owner,
  ]);

  function cleanupScreen() {
    localScreen.current?.cleanup();
    localScreen.current = null;
  }

  useEffect(() => {
    mounted.current = true;
    const onPageHide = () => {
      const id = localScreen.current?.id;
      cleanupScreen();
      if (id) navigator.sendBeacon(`/api/capture/${id}/stop`);
    };
    const onVisibility = () => {
      if (
        document.visibilityState === "hidden" &&
        localScreen.current?.kind === "camera"
      ) {
        const id = localScreen.current.id;
        setError(
          "La c\u00e1mara se detuvo al ocultar la pesta\u00f1a. Vuelve a conectarla para continuar.",
        );
        void stopId(id).catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisibility);
      onPageHide();
    };
  }, []);

  useEffect(() => {
    if (
      localScreen.current &&
      (capture.capture_id !== localScreen.current.id ||
        capture.state !== "running")
    ) {
      cleanupScreen();
    }
  }, [capture.capture_id, capture.state]);

  async function stopId(id: string) {
    cleanupScreen();
    const response = await fetch(`/api/capture/${id}/stop`, {
      method: "POST",
      signal: AbortSignal.timeout(10000),
    });
    const next = await readResponse<CaptureStatus>(response);
    if (mounted.current) applyCapture(next);
  }

  async function startFile(file: File, fps: number) {
    if (file.size > 256 * 1024 * 1024) {
      setError("El tamaño máximo de vídeo es 256 MB.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("capture_fps", String(fps || 10));
      body.append("sampling_mode", fps === 0 ? "adaptive" : "fixed");
      const response = await fetch("/api/capture/file", {
        method: "POST",
        body,
        signal: AbortSignal.timeout(120000),
      });
      const next = await readResponse<CaptureStatus>(response);
      if (mounted.current) applyCapture(next);
    } catch (cause) {
      if (mounted.current)
        setError(
          cause instanceof Error ? cause.message : "No se pudo abrir el vídeo.",
        );
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function startScreen(fps: number) {
    return startBrowser(fps, "screen");
  }
  async function startCamera(fps: number, facing: "environment" | "user") {
    return startBrowser(fps, "camera", facing);
  }
  async function startBrowser(
    fps: number,
    kind: "screen" | "camera",
    facing: "environment" | "user" = "environment",
  ) {
    setBusy(true);
    setError(null);
    let stream: MediaStream | undefined;
    let id: string | null = null;
    try {
      if (
        kind === "camera" &&
        (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
      )
        throw new Error(
          "Para usar la c\u00e1mara abre la app por HTTPS y conf\u00eda en su certificado local. Consulta la gu\u00eda de acceso desde el m\u00f3vil.",
        );
      if (kind === "screen" && !navigator.mediaDevices?.getDisplayMedia)
        throw new Error(
          "Este navegador no permite compartir pantalla aquí. Abre la aplicación en Chrome o Edge desde localhost o HTTPS.",
        );
      // Must be invoked from the click gesture, before any network await.
      stream =
        kind === "camera"
          ? await navigator.mediaDevices.getUserMedia({
              video: {
                facingMode: { ideal: facing },
                width: { ideal: 1920 },
                height: { ideal: 1080 },
                frameRate: { ideal: fps || 10, max: 15 },
              },
              audio: false,
            })
          : await navigator.mediaDevices.getDisplayMedia({
              video: { frameRate: fps || 10 },
              audio: false,
            });
      if (!mounted.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      if (
        kind === "camera" &&
        (document.visibilityState === "hidden" ||
          stream.getVideoTracks()[0]?.readyState !== "live")
      ) {
        throw new Error(
          "Mantén la pestaña visible y la cámara activa para iniciar la captura.",
        );
      }
      const surface = stream.getVideoTracks()[0].getSettings().displaySurface;
      const actualFacing = stream.getVideoTracks()[0].getSettings().facingMode;
      const sourceName =
        kind === "camera"
          ? actualFacing === "environment"
            ? "C\u00e1mara trasera"
            : actualFacing === "user"
              ? "Cámara frontal"
              : "Cámara del dispositivo"
          : surface === "browser"
            ? "Pestaña compartida"
            : surface === "window"
              ? "Ventana compartida"
              : "Pantalla compartida";
      const response = await fetch(`/api/capture/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capture_fps: fps || 10,
          sampling_mode: fps === 0 ? "adaptive" : "fixed",
          name: sourceName,
        }),
        signal: AbortSignal.timeout(10000),
      });
      const next = await readResponse<CaptureStatus>(response);
      id = next.capture_id!;
      if (
        !mounted.current ||
        (kind === "camera" && document.visibilityState === "hidden")
      ) {
        stream.getTracks().forEach((track) => track.stop());
        await stopId(id);
        return;
      }
      const activeId = id;
      const end = () => {
        void stopId(activeId).catch(() =>
          setError("No se pudo confirmar la parada en el servidor."),
        );
      };
      const cleanup = sendScreen(
        stream,
        id,
        fps || 10,
        end,
        (cause) => {
          setError(cause.message);
          end();
        },
        kind,
      );
      localScreen.current = { id, kind, cleanup };
      applyCapture(next);
    } catch (cause) {
      stream?.getTracks().forEach((track) => track.stop());
      if (id) void stopId(id).catch(() => {});
      if (mounted.current)
        setError(
          cause instanceof DOMException && cause.name === "NotAllowedError"
            ? kind === "camera"
              ? "Permiso de c\u00e1mara denegado. Permite su uso en los ajustes del navegador y vuelve a intentarlo."
              : "No se compartió ninguna pantalla. Puedes volver a abrir el selector."
            : kind === "camera" &&
                cause instanceof DOMException &&
                cause.name === "NotFoundError"
              ? "No se ha encontrado ninguna c\u00e1mara en este dispositivo."
              : kind === "camera" &&
                  cause instanceof DOMException &&
                  cause.name === "NotReadableError"
                ? "No se puede abrir la c\u00e1mara. Comprueba que otra app no la est\u00e9 utilizando."
                : cause instanceof DOMException &&
                    cause.name === "NotSupportedError"
                  ? kind === "camera"
                    ? "Este navegador no admite la cámara aquí. Prueba Safari en iPhone o Chrome en Android."
                    : "Este navegador no admite compartir pantalla. Prueba con Chrome o Edge."
                  : cause instanceof Error
                    ? cause.message
                    : "No se pudo conectar la fuente de vídeo.",
        );
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function stop() {
    if (!capture.capture_id) return;
    setBusy(true);
    setError(null);
    try {
      await stopId(capture.capture_id);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudo detener la captura.",
      );
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <CaptureContext.Provider
      value={{
        capture,
        busy,
        error,
        available,
        uiLatency,
        startFile,
        startScreen,
        startCamera,
        stop,
      }}
    >
      {children}
    </CaptureContext.Provider>
  );
}

export function useCapture() {
  const value = useContext(CaptureContext);
  if (!value) throw new Error("CaptureProvider is required");
  return value;
}
