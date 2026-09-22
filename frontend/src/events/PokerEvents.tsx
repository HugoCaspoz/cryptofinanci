import { useCapture } from "../capture/CaptureProvider";
import { useState } from "react";

export const eventLabels: Record<string, string> = {
  GAME_STATE_UPDATED: "Estado actualizado",
  HOLE_CARDS_DETECTED: "Cartas de Hero confirmadas",
  HERO_CARDS_CLEARED: "Cartas de Hero retiradas",
  BOARD_CARDS_CLEARED: "Board retirado",
  BOARD_CARDS_UPDATED: "Board actualizado",
  FLOP_DEALT: "Flop confirmado",
  TURN_DEALT: "Turn confirmado",
  RIVER_DEALT: "River confirmado",
  HAND_STARTED: "Mano iniciada",
  HERO_DECISION_REQUIRED: "Turno de decisión de Hero",
  HAND_FINISHED: "Mano terminada",
  CAPTURE_ENDED: "Observación interrumpida",
  PLAYER_FOLDED: "Fold",
  PLAYER_CHECKED: "Check",
  PLAYER_CALLED: "Call",
  PLAYER_BET: "Bet",
  PLAYER_RAISED: "Raise",
  PLAYER_ALL_IN: "All-in",
};

export function PokerEvents() {
  const { capture, available } = useCapture();
  const stream = capture.observation_state.event_stream;
  const players = capture.observation_state.game_state?.players || [];
  const actions = capture.observation_state.actions;
  const [showChanges, setShowChanges] = useState(false);
  const visibleEvents = (stream?.events || []).filter(
    (event) => showChanges || event.type !== "GAME_STATE_UPDATED",
  );
  const sourceTime = (seconds: number) =>
    [
      Math.floor(seconds / 3600),
      Math.floor(seconds / 60) % 60,
      Math.floor(seconds) % 60,
    ]
      .map((value) => String(value).padStart(2, "0"))
      .join(":");
  return (
    <section className="panel poker-events" aria-label="Eventos de la partida">
      <div className="section-heading">
        <div>
          <span className="eyebrow">EVENTOS EN DIRECTO</span>
          <h2>Eventos de la partida</h2>
        </div>
        <span className="outline-badge" data-testid="poker-event-count">
          {stream?.event_count ?? 0} eventos
        </span>
      </div>
      <p className="card-footnote">
        Cartas, límites de mano y acciones inferidas al coincidir turno visual,
        etiqueta, stack, apuesta y bote. Los tramos sin evidencia suficiente
        pueden quedar incompletos.
      </p>
      <label className="event-filter">
        <input
          type="checkbox"
          checked={showChanges}
          onChange={(event) => setShowChanges(event.target.checked)}
        />{" "}
        Incluir cambios de estado
      </label>
      <p data-testid="action-summary">
        {actions?.event_count ?? 0} acciones reconstruidas en esta captura.
      </p>
      {actions?.reason && (
        <p className="card-notice">
          {actions.reason === "multiple_active_players"
            ? "Hay varios indicadores de turno. No se puede atribuir la acción."
            : actions.reason === "evidence_timeout"
              ? "La evidencia no llegó a tiempo. No se ha registrado una acción."
              : "Esperando lecturas concordantes para confirmar la acción."}
        </p>
      )}
      {actions?.status === "unsupported_profile" && (
        <p className="card-notice">
          Este perfil todavía no tiene reconocimiento de etiquetas y turno.
        </p>
      )}
      {!available ? (
        <p className="card-notice">
          Sin conexión. Este historial puede estar desactualizado.
        </p>
      ) : capture.state !== "running" && (stream?.event_count || 0) > 0 ? (
        <p className="card-notice">
          Historial conservado de la captura terminada o detenida.
        </p>
      ) : null}
      {(stream?.dropped_events || 0) > 0 && (
        <p className="card-notice">
          {stream?.dropped_events} eventos anteriores ya no están en memoria. La
          exportación incluye un estado de referencia para reproducir el tramo
          disponible.
        </p>
      )}
      {!visibleEvents.length ? (
        <p className="card-footnote">Esperando cambios confirmados.</p>
      ) : (
        <ol className="poker-event-list">
          {[...visibleEvents].reverse().map((event) => {
            const player = players.find((p) => p.player_id === event.player_id);
            return (
              <li
                key={`${event.scope_id}:${event.sequence}`}
                data-testid="poker-event"
                data-event-type={event.type}
              >
                <div>
                  <span className="muted">
                    {sourceTime(event.timestamp)} · #{event.sequence}
                  </span>
                  <strong>
                    {player
                      ? `${player.nickname || `Asiento ${player.seat}`} · `
                      : ""}
                    {eventLabels[event.type] || event.type}
                    {event.amount !== null
                      ? ` · ${event.amount}${event.unit ? ` ${event.unit}` : ""}`
                      : ""}
                  </strong>
                </div>
                <small>
                  {player ? `Asiento ${player.seat} · ` : ""}
                  {event.amount !== null
                    ? `Apuesta total ${event.amount}${event.unit ? ` ${event.unit}` : ""} · `
                    : ""}
                  Frame {event.frame_id} ·{" "}
                  {event.confidence === null
                    ? "Sin confianza agregada"
                    : `Confianza ${Math.round(event.confidence * 100)}%`}
                </small>
                {!!event.action_evidence?.length && (
                  <small>
                    Señales: turno visual, etiqueta, stack, apuesta y bote.
                  </small>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {stream && (
        <a
          className="text-link"
          href={`/api/events?scope_id=${encodeURIComponent(stream.scope_id)}`}
          download={`zeros-events-${stream.scope_id}.json`}
        >
          Exportar historial disponible (JSON)
        </a>
      )}
      <p className="card-footnote">
        Últimos {stream?.capacity ?? 40} eventos en memoria. Tiempos relativos
        al vídeo (HH:MM:SS); la confianza no es una probabilidad calibrada. Una
        captura nueva reinicia el historial.
      </p>
    </section>
  );
}
