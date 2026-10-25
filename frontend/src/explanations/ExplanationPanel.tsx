import { useEffect, useRef, useState } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";
import "./explanations.css";

type Explanation = {
  style: "simple" | "advanced";
  provider: "local" | "openai";
  fallback_reason: string | null;
  paragraphs: { fact_id: string; text: string; source: string }[];
};

export function ExplanationPanel({ identity }: { identity: string }) {
  const { capture, available } = useCapture();
  const [style, setStyle] = useState<"simple" | "advanced">("simple");
  const [data, setData] = useState<{ key: string; value: Explanation } | null>(
    null,
  );
  const [error, setError] = useState<{ key: string; message: string } | null>(
    null,
  );
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const allowed =
    available &&
    (capture.decisions?.visibility === "training" ||
      capture.feedback?.review_blocked === false);
  const key = JSON.stringify([
    identity,
    style,
    capture.server_id,
    capture.capture_id,
    capture.feedback?.revision,
    allowed,
  ]);
  useEffect(() => {
    activeRequest.current?.abort();
    setData(null);
    setError(null);
    return () => activeRequest.current?.abort();
  }, [key]);
  async function generate() {
    if (!allowed) return;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setBusyKey(key);
    setError(null);
    try {
      const result = await readResponse<Explanation>(
        await fetch(`/api/decisions/${identity}/explanation`, {
          method: "POST",
          signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ style }),
        }),
      );
      if (!controller.signal.aborted) setData({ key, value: result });
    } catch (cause) {
      if (!controller.signal.aborted)
        setError({
          key,
          message:
            cause instanceof Error
              ? cause.message
              : "No se pudo generar la explicación.",
        });
    } finally {
      if (activeRequest.current === controller) setBusyKey(null);
    }
  }
  const result = allowed && data?.key === key ? data.value : null;
  return (
    <section
      className="explanation-panel"
      aria-label="Explicación de la decisión"
    >
      <h3>Entender la decisión</h3>
      <p>
        Una lectura de los resultados guardados del motor, con sus supuestos y
        límites.
      </p>
      <div className="explanation-controls">
        <label>
          Detalle de la explicación
          <select
            value={style}
            onChange={(event) => setStyle(event.target.value as typeof style)}
          >
            <option value="simple">Simple</option>
            <option value="advanced">Avanzado</option>
          </select>
        </label>
        <button
          type="button"
          className="button secondary"
          disabled={!allowed || busyKey === key}
          onClick={() => void generate()}
        >
          {busyKey === key
            ? "Preparando explicación..."
            : "Generar explicación"}
        </button>
      </div>
      {!allowed && (
        <p>
          La explicación no está disponible mientras la revisión está bloqueada
          o no hay conexión.
        </p>
      )}
      {error?.key === key && <p role="alert">{error.message}</p>}
      {result && (
        <div data-testid="decision-explanation">
          <p className="explanation-source">
            {result.provider === "openai"
              ? "Organizada con OpenAI"
              : "Explicación local"}
          </p>
          {result.fallback_reason && (
            <p role="status">{result.fallback_reason}</p>
          )}
          {result.paragraphs.map((paragraph) => (
            <p key={paragraph.fact_id}>{paragraph.text}</p>
          ))}
        </div>
      )}
    </section>
  );
}
