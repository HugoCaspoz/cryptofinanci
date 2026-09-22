import { Link } from "react-router";
import { useCapture } from "../capture/CaptureProvider";
import { handLabels } from "./types";

export function HandPanel() {
  const { capture } = useCapture();
  const tracking = capture.observation_state.hands;
  const state = capture.observation_state.game_state;
  return (
    <section className="panel hand-panel" aria-label="Seguimiento de manos">
      <div className="section-heading">
        <div>
          <span className="eyebrow">LÍMITES DE MANO</span>
          <h2>Manos observadas</h2>
        </div>
        <strong data-testid="hand-status">
          {handLabels[state?.hand_status || "unidentified"]}
        </strong>
      </div>
      <p>
        <span data-testid="hands-started">{tracking?.started_count ?? 0}</span>{" "}
        iniciadas ·{" "}
        <span data-testid="hands-finished">
          {tracking?.finished_count ?? 0}
        </span>{" "}
        terminadas en esta captura.
      </p>
      {tracking?.active_hand?.partial_start && (
        <p className="card-notice">
          La captura puede haber empezado con esta mano en curso. Su inicio es
          parcial.
        </p>
      )}
      {tracking?.boundary_pending && (
        <p className="card-notice">
          Comprobando si las cartas retiradas indican un final de mano.
        </p>
      )}
      {capture.hand_storage?.error && (
        <p className="card-notice">{capture.hand_storage.error}</p>
      )}
      <p className="card-footnote">
        Una ocultación o un fold de Hero no bastan para cerrar una mano. Si la
        captura termina antes de confirmar su final, se guarda como incompleta.
      </p>
      <Link
        className="text-link"
        to={`/hands${state ? `?scope_id=${state.scope_id}` : ""}`}
      >
        Ver manos guardadas de esta captura →
      </Link>
    </section>
  );
}
