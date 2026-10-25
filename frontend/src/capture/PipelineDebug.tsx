import type { LatencySummary } from "../live/latency";
import { useCapture } from "./CaptureProvider";

const ms = (value: number | null | undefined) =>
  value == null ? "—" : `${value.toFixed(1)} ms`;

export function PipelineDebug() {
  const { capture, available, uiLatency } = useCapture();
  const metrics = capture.pipeline;
  return (
    <details className="panel pipeline-debug">
      <summary>
        <span>Depuración del pipeline</span>
        <span className="debug-status">
          {!available
            ? "Sin conexión"
            : metrics?.active
              ? "En ejecución"
              : "En espera"}
        </span>
      </summary>
      <div className="debug-body">
        {capture.session_health?.archive_error && (
          <p role="alert">{capture.session_health.archive_error}</p>
        )}
        {capture.session_health && (
          <p data-testid="session-health">
            Memoria del proceso:{" "}
            {capture.session_health.process_rss_bytes == null
              ? "No disponible"
              : `${(capture.session_health.process_rss_bytes / 1048576).toFixed(1)} MiB RSS`}{" "}
            · Tiempo de fuente:{" "}
            {(capture.session_health.source_seconds / 3600).toFixed(2)} h ·
            Imágenes importantes guardadas:{" "}
            {capture.session_health.important_frames_saved} · Perfiles en
            memoria: {capture.session_health.retained.opponent_profiles} /{" "}
            {capture.session_health.limits.opponent_profiles}.
          </p>
        )}

        <p>
          {metrics?.sampling?.mode === "adaptive"
            ? `Muestreo inteligente: ${metrics.sampling.target_fps} FPS · ${metrics.sampling.skipped_frames} frames omitidos antes del OCR.`
            : "Muestreo fijo"}
        </p>
        <p>Captura → Cola limitada → Procesamiento → Observaciones</p>
        {!available && (
          <p role="alert">
            Sin datos actuales del servidor. Los valores mostrados son los
            últimos recibidos.
          </p>
        )}
        <div className="debug-grid">
          <div>
            <span>FPS enviados al procesamiento</span>
            <strong data-testid="capture-fps">
              {metrics?.capture_fps.toFixed(1) ?? "—"}
            </strong>
            <small>
              Objetivo: {metrics?.sampling?.target_fps ?? capture.capture_fps}{" "}
              FPS
            </small>
          </div>
          <div>
            <span>FPS de procesamiento</span>
            <strong data-testid="processing-fps">
              {metrics?.processing_fps.toFixed(1) ?? "—"}
            </strong>
            <small>Ventana móvil de 5 segundos</small>
          </div>
          <div>
            <span>Frames en cola</span>
            <strong data-testid="queue-size">
              {metrics
                ? `${metrics.queue_size} / ${metrics.queue_capacity}`
                : "—"}
            </strong>
            <small>
              Máximo observado: {metrics?.queue_high_watermark ?? "—"}
            </small>
          </div>
          <div>
            <span>Descartados por antigüedad</span>
            <strong data-testid="dropped-frames">
              {metrics?.dropped_frames ?? "—"}
            </strong>
            <small>Se prioriza el frame más reciente</small>
          </div>
          <div>
            <span>Latencia de procesamiento</span>
            <strong data-testid="processing-latency">
              {ms(metrics?.processing_latency_ms)}
            </strong>
            <small>Media: {ms(metrics?.mean_processing_latency_ms)}</small>
          </div>
          <div>
            <span>Espera antes de procesar</span>
            <strong>{ms(metrics?.queue_wait_ms)}</strong>
            <small>Desde que el frame está disponible</small>
          </div>
          <div>
            <span>Latencia del frame</span>
            <strong>{ms(metrics?.frame_latency_ms)}</strong>
            <small>Espera + procesamiento en backend</small>
          </div>
          <div>
            <span>Capturados / procesados</span>
            <strong data-testid="processed-frames">
              {metrics
                ? `${metrics.captured_frames} / ${metrics.processed_frames}`
                : "—"}
            </strong>
            <small>
              En proceso: {metrics?.in_flight ?? 0} · Fallidos:{" "}
              {metrics?.failed_frames ?? 0}
            </small>
          </div>
        </div>
        <h3>Latencias por etapa</h3>
        <p>
          Último valor, media y P95 de hasta 128 muestras por etapa. Objetivos
          de ingeniería, no garantías.
        </p>
        <div className="latency-table-scroll">
          <table className="latency-table" aria-label="Latencias por etapa">
            <thead>
              <tr>
                <th>Etapa</th>
                <th>Última</th>
                <th>Media</th>
                <th>P95</th>
                <th>Muestras</th>
                <th>Frame</th>
                <th>Objetivo P95</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["capture", "Captura / decodificación"],
                  ["vision", "Visión (incluye OCR)"],
                  ["preview", "Preparar imagen"],
                  ["state", "Actualizar estado"],
                  ["publish", "Preparar estado y guardar"],
                  ["total_backend", "Total backend hasta estado listo"],
                  ["equity", "Motor matemático"],
                  ["strategy", "Motor de estrategia"],
                  ["equity_total", "Hasta análisis matemático"],
                  ["strategy_total", "Hasta estrategia archivada"],
                  ["ui", "Interfaz: recepción a render"],
                ] as const
              ).map(([name, label]) => {
                const value: LatencySummary | null | undefined =
                  name === "ui" ? uiLatency : metrics?.latencies?.[name];
                return (
                  <tr key={name} data-testid={`latency-${name}`}>
                    <th scope="row">{label}</th>
                    <td>{ms(value?.last_ms)}</td>
                    <td>{ms(value?.mean_ms)}</td>
                    <td>{ms(value?.p95_ms)}</td>
                    <td>{value?.samples ?? 0}</td>
                    <td>{value?.frame_id ?? "—"}</td>
                    <td>
                      {value?.target_ms == null ? (
                        "—"
                      ) : (
                        <span
                          className={
                            value.within_target == null
                              ? ""
                              : value.within_target
                                ? "latency-ok"
                                : "latency-over"
                          }
                        >
                          &lt; {value.target_ms} ms
                          {value.within_target == null
                            ? " · Sin muestras"
                            : value.within_target
                              ? " · Cumple"
                              : " · Superado"}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="debug-footnote">
          El estado está incluido en publicación. Los análisis son asíncronos y
          pueden pertenecer a otro frame; no se suman al total. Los tiempos del
          navegador y servidor se muestran por separado.
        </p>
        <p className="debug-footnote">
          La captura mide lectura/decodificación en el backend: no incluye la
          selección de pantalla, codificación del navegador ni subida. La medida
          UI aproxima un pintado tras recibir el snapshot, sin medir red ni la
          descarga JPEG. Solo se muestrean pestañas visibles.
        </p>
        <p className="debug-footnote">
          Contadores por captura. Descartados al parar:{" "}
          {metrics?.discarded_frames ?? 0}. Los FPS requieren un segundo de
          muestra y pasan a cero al terminar. La latencia no incluye el trayecto
          de red ni la visualización en el navegador.
        </p>
        <p className="debug-footnote">
          Visión y estado: reconocimiento de cartas por referencias y
          confirmación temporal. Consulta el perfil activo y las lecturas en
          «Cartas observadas». Detección automática de mesa pendiente.
        </p>
      </div>
    </details>
  );
}
