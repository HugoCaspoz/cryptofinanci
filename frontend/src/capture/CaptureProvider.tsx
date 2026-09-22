import { createContext, useContext, useEffect, useRef, useState } from "react";
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
  startFile: (file: File, fps: number) => Promise<void>;
  startScreen: (fps: number) => Promise<void>;
  stop: () => Promise<void>;
};

const CaptureContext = createContext<CaptureContextValue | null>(null);

export function CaptureProvider({ children }: { children: ReactNode }) {
  const [capture, setCapture] = useState(emptyCapture);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { captureSnapshot, captureReady, status } = useLive();
  const available = captureReady && status === "connected";
  const localScreen = useRef<{ id: string; cleanup: () => void } | null>(null);
  const mounted = useRef(true);
  function applyCapture(next: CaptureStatus, fromStream = false) {
    setCapture((current) => {
      if (next.server_id !== current.server_id) {
        return fromStream || !current.server_id ? next : current;
      }
      return next.revision >= current.revision ? next : current;
    });
  }

  useEffect(() => {
    if (captureSnapshot) applyCapture(captureSnapshot, true);
  }, [captureSnapshot]);

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
    window.addEventListener("pagehide", onPageHide);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", onPageHide);
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
      body.append("capture_fps", String(fps));
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
    setBusy(true);
    setError(null);
    let stream: MediaStream | undefined;
    let id: string | null = null;
    try {
      if (!navigator.mediaDevices?.getDisplayMedia)
        throw new Error(
          "Este navegador no permite compartir pantalla aquí. Abre la aplicación en Chrome o Edge desde localhost o HTTPS.",
        );
      // Must be invoked from the click gesture, before any network await.
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: fps },
        audio: false,
      });
      if (!mounted.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const surface = stream.getVideoTracks()[0].getSettings().displaySurface;
      const sourceName =
        surface === "browser"
          ? "Pestaña compartida"
          : surface === "window"
            ? "Ventana compartida"
            : "Pantalla compartida";
      const response = await fetch("/api/capture/screen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capture_fps: fps,
          name: sourceName,
        }),
        signal: AbortSignal.timeout(10000),
      });
      const next = await readResponse<CaptureStatus>(response);
      id = next.capture_id!;
      if (!mounted.current) {
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
      const cleanup = sendScreen(stream, id, fps, end, (cause) => {
        setError(cause.message);
        end();
      });
      localScreen.current = { id, cleanup };
      applyCapture(next);
    } catch (cause) {
      stream?.getTracks().forEach((track) => track.stop());
      if (id) void stopId(id).catch(() => {});
      if (mounted.current)
        setError(
          cause instanceof DOMException && cause.name === "NotAllowedError"
            ? "No se compartió ninguna pantalla. Puedes volver a abrir el selector."
            : cause instanceof DOMException &&
                cause.name === "NotSupportedError"
              ? "Este navegador no admite compartir pantalla. Prueba con Chrome o Edge."
              : cause instanceof Error
                ? cause.message
                : "No se pudo compartir la pantalla.",
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
      value={{ capture, busy, error, available, startFile, startScreen, stop }}
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
