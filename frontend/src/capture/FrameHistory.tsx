import { useState } from "react";
import { useCapture } from "./CaptureProvider";

type Entry = {
  frame_id: number;
  timestamp: number;
  width: number;
  height: number;
};

export function FrameHistory() {
  const { capture, available } = useCapture();
  // A new capture mounts a fresh viewer, so an earlier image cannot cross scopes.
  return (
    <History
      key={`${capture.server_id}:${capture.capture_id}`}
      id={capture.capture_id}
      available={available}
    />
  );
}

function History({ id, available }: { id: string | null; available: boolean }) {
  const { capture } = useCapture();
  const buffer = capture.pipeline?.buffer;
  const [frames, setFrames] = useState<Entry[]>([]);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const frame = frames[selected];
  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/capture/${id}/buffer`, {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error();
      const result = await response.json();
      setFrames(result.frames);
      setSelected(Math.max(0, result.frames.length - 1));
    } catch {
      setError("No se pudo consultar el historial. Vuelve a actualizarlo.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="panel pipeline-debug">
      <summary>Historial temporal de imágenes</summary>
      <div className="debug-body">
        <p>
          Imágenes de la fuente, sin volver a analizar la partida. Ventana:{" "}
          {buffer?.seconds ?? 10} segundos; {buffer?.frames ?? 0} frames
          conservados.
        </p>
        <button
          className="button secondary"
          disabled={!id || !available || busy}
          onClick={() => void refresh()}
        >
          Actualizar historial
        </button>
        {frames.length > 0 && (
          <>
            <label>
              Frame del historial
              <input
                type="range"
                min={0}
                max={frames.length - 1}
                value={selected}
                onChange={(event) => {
                  setSelected(Number(event.target.value));
                  setError("");
                }}
              />
            </label>
            <p>
              Frame {frame.frame_id} · {frame.timestamp.toFixed(3)} s de la
              fuente · {frame.width} × {frame.height}
            </p>
            <img
              key={frame.frame_id}
              src={`/api/capture/${id}/buffer/frames/${frame.frame_id}`}
              alt={`Frame histórico ${frame.frame_id}`}
              style={{ maxWidth: "100%", height: "auto" }}
              onError={() =>
                setError(
                  "Este frame ya no está disponible. Actualiza el historial.",
                )
              }
            />
          </>
        )}
        {!busy && id && frames.length === 0 && (
          <p>Actualiza para consultar los frames disponibles.</p>
        )}
        {error && <p role="alert">{error}</p>}
        <p>
          El historial se sustituye al iniciar otra captura. Los límites de
          memoria pueden acortar la ventana conservada.
        </p>
      </div>
    </details>
  );
}
