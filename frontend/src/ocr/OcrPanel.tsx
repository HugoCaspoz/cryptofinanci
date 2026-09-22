import { useCapture } from "../capture/CaptureProvider";
import type { OcrField } from "./types";

const reasons: Record<string, string> = {
  waiting: "Esperando imágenes para leer la mesa.",
  not_configured: "Esperando una fuente de vídeo.",
  layout_unavailable:
    "No se pudo cargar el layout para OCR. Revisa la configuración y reinicia la captura.",
  uncalibrated_layout:
    "Confirma la calibración del layout y reinicia la captura para leer esta plataforma.",
  resolution_mismatch: "OCR pausado: se requiere una captura de 1920 × 1080.",
  engine_unavailable:
    "El motor OCR no está instalado en el backend. Usa Docker o configura Tesseract y reinicia la captura.",
  engine_error:
    "El motor OCR no pudo leer la muestra. Se conserva el último resultado y se reintentará.",
  engine_timeout:
    "La lectura OCR superó el tiempo límite. Se conserva el último resultado y se reintentará.",
};

function Field({
  label,
  field,
  id,
}: {
  label: string;
  field?: OcrField;
  id: string;
}) {
  return (
    <div className={`ocr-field ${field?.status || "waiting"}`}>
      <dt>{label}</dt>
      <dd>
        <strong data-testid={`ocr-${id}`}>
          {field?.value ?? "—"}
          {field?.value !== null && field?.unit ? ` ${field.unit}` : ""}
        </strong>
        <small>
          {field?.status === "confirmed"
            ? `Confirmado · ${Math.round(field.confidence * 100)}% OCR`
            : field?.status === "pending"
              ? "Cambio pendiente de confirmar"
              : field?.value != null
                ? "No legible · Último valor conservado"
                : "Sin lectura confirmada"}
        </small>
      </dd>
    </div>
  );
}

export function OcrPanel() {
  const { capture, available } = useCapture();
  const ocr = capture.observation_state.ocr;
  return (
    <section className="panel ocr-panel" aria-label="Lectura OCR de la mesa">
      <div className="section-heading">
        <div>
          <span className="eyebrow">TEXTO E IMPORTES</span>
          <h2>Lecturas de la mesa</h2>
        </div>
        <span className="outline-badge">Tesseract · Hasta 2 muestras/s</span>
      </div>
      {ocr?.status !== "ready" && (
        <p className="card-notice">
          {reasons[ocr?.status || "waiting"] || "OCR no disponible."}
        </p>
      )}
      {!available ? (
        <p className="card-notice">
          Sin conexión. Los valores mostrados pueden estar desactualizados.
        </p>
      ) : capture.state !== "running" && ocr?.last_sample_frame_id != null ? (
        <p className="card-notice">
          Últimas lecturas de la captura terminada o detenida.
        </p>
      ) : null}
      <dl className="ocr-summary">
        <Field label="Bote" id="pot" field={ocr?.fields.pot} />
        <Field label="Ciegas" id="blinds" field={ocr?.fields.blinds} />
      </dl>
      <div className="ocr-players">
        {Array.from({ length: 6 }, (_, index) => (
          <article key={index}>
            <h3>Asiento {index + 1}</h3>
            <dl>
              {[
                ["nickname", "Nombre"],
                ["stack", "Stack"],
                ["bet", "Apuesta"],
              ].map(([key, label]) => (
                <Field
                  key={key}
                  label={label}
                  id={`players.${index}.${key}`}
                  field={ocr?.fields[`players.${index}.${key}`]}
                />
              ))}
            </dl>
          </article>
        ))}
      </div>
      <p className="card-footnote">
        Confirmación por 3 coincidencias entre las últimas 5 muestras, con
        confianza mínima del 80%. Una zona vacía o ilegible no significa cero.
        Las cifras sin unidad visible se conservan sin asumir moneda o fichas.
      </p>
      <p className="card-footnote">
        Separador decimal configurado:{" "}
        {ocr?.decimal_separator === "," ? "coma" : "punto"}. La confianza OCR no
        es una probabilidad calibrada. Reinicia la captura para aplicar cambios
        de layout.
      </p>
      <details className="ocr-diagnostics">
        <summary>Ver lecturas originales y confianza</summary>
        <p className="card-footnote">
          Última muestra:{" "}
          {ocr?.last_sample_timestamp != null
            ? `${ocr.last_sample_timestamp.toFixed(1)} s · frame ${ocr.last_sample_frame_id}`
            : "pendiente"}
        </p>
        <div className="ocr-table-scroll">
          <table>
            <thead>
              <tr>
                <th>Región</th>
                <th>Texto leído</th>
                <th>Confianza actual</th>
                <th>Última confirmación</th>
              </tr>
            </thead>
            <tbody>
              {Object.values(ocr?.fields || {}).map((field) => (
                <tr key={field.key}>
                  <td>{field.key}</td>
                  <td>{field.raw_text || "(sin texto)"}</td>
                  <td>{Math.round(field.latest_confidence * 100)}%</td>
                  <td>
                    {field.confirmed_timestamp == null
                      ? "—"
                      : `${field.confirmed_timestamp.toFixed(1)} s`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
