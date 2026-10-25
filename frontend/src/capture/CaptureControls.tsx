import { useState } from "react";
import { useCapture } from "./CaptureProvider";

export function CaptureControls() {
  const {
    capture,
    busy,
    error,
    available,
    startFile,
    startScreen,
    startCamera,
    stop,
  } = useCapture();
  const [fps, setFps] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const running = capture.state === "running";
  const disabled = busy || running || !available;
  return (
    <section className="panel capture-controls">
      <div>
        <span className="eyebrow">FUENTE DE VÍDEO</span>
        <h2>Conecta tu mesa</h2>
        <p>Conecta un archivo, una ventana o la cámara de tu móvil.</p>
      </div>
      <div className="capture-options">
        <label className="fps-control">
          FPS de captura
          <select
            value={fps}
            disabled={disabled}
            onChange={(event) => setFps(Number(event.target.value))}
          >
            <option value={0}>Inteligente: 2 / 10 FPS</option>
            {[1, 2, 5, 10, 15].map((value) => (
              <option key={value} value={value}>
                {value} FPS
              </option>
            ))}
          </select>
        </label>
        <label className="file-control">
          Archivo de vídeo
          <input
            type="file"
            accept=".mp4,.mov,.mkv,.avi,.webm"
            disabled={disabled}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <div className="capture-actions">
          <label>
            Cámara
            <select
              aria-label="Cámara"
              value={facing}
              disabled={disabled}
              onChange={(event) =>
                setFacing(event.target.value as "environment" | "user")
              }
            >
              <option value="environment">Trasera (recomendada)</option>
              <option value="user">Frontal</option>
            </select>
          </label>
          <button
            className="button primary"
            disabled={disabled}
            onClick={() => void startCamera(fps, facing)}
          >
            Usar cámara
          </button>
          <button
            className="button primary"
            disabled={disabled || !file}
            onClick={() => file && void startFile(file, fps)}
          >
            Reproducir archivo
          </button>
          <button
            className="button secondary"
            disabled={disabled}
            onClick={() => void startScreen(fps)}
          >
            Compartir pantalla o ventana
          </button>
          <button
            className="button stop-button"
            disabled={busy || !running}
            onClick={() => void stop()}
          >
            Detener captura
          </button>
        </div>
      </div>
      <p className="capture-help">
        Hasta 256 MB · Sin audio · Detén la fuente actual antes de cambiarla.{" "}
        {running
          ? "La captura continúa al navegar entre páginas."
          : "El archivo se sube antes de iniciar su reproducción."}
      </p>
      <p className="capture-help">
        Cámara: coloca el móvil fijo y en horizontal, con una sola mesa de
        frente y sin reflejos. Mantén esta pestaña visible; la cámara se detiene
        al ocultarla o bloquear el móvil. Ajusta las regiones de la mesa sobre
        la imagen recibida. Desde otro dispositivo necesitas HTTPS.{" "}
        <a
          className="text-link"
          href="/mobile-setup.html"
          target="_blank"
          rel="noreferrer"
        >
          Configurar acceso desde el móvil
        </a>
      </p>
      {busy && <p role="status">Preparando la fuente…</p>}
      {!available && (
        <p role="alert">
          No se puede consultar la captura. Comprobando conexión…
        </p>
      )}
      {(error || capture.error) && (
        <p className="capture-error" role="alert">
          {error || capture.error}
        </p>
      )}
    </section>
  );
}
