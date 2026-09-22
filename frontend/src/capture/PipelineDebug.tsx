import { useCapture } from "./CaptureProvider";

const ms = (value: number | null | undefined) =>
  value == null ? "—" : `${value.toFixed(1)} ms`;

export function PipelineDebug() {
  const { capture, available } = useCapture();
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
        <p>Captura → Cola limitada → Procesamiento → Observaciones</p>
        {!available && (
          <p role="alert">
            Sin datos actuales del servidor. Los valores mostrados son los
            últimos recibidos.
          </p>
        )}
        <div className="debug-grid">
          <div>
            <span>FPS de captura reales</span>
            <strong data-testid="capture-fps">
              {metrics?.capture_fps.toFixed(1) ?? "—"}
            </strong>
            <small>Objetivo: {capture.capture_fps} FPS</small>
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
