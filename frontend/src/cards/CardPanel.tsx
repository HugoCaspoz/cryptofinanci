import { useCapture } from "../capture/CaptureProvider";
import { cardText, suits, type CardRegion } from "./types";

const reasons: Record<string, string> = {
  not_configured: "Esperando una fuente de vídeo.",
  layout_unavailable:
    "No se pudo cargar el layout. Corrígelo y reinicia la captura.",
  templates_unavailable:
    "No se pudieron cargar las 52 referencias. Revisa el perfil y reinicia la captura.",
  platform_mismatch:
    "El layout y las referencias pertenecen a plataformas distintas. Configura las referencias adecuadas y reinicia la captura.",
  uncalibrated_layout:
    "Comprueba y guarda la calibración del layout antes de reiniciar la captura.",
  resolution_mismatch:
    "Reconocimiento pausado: se requiere una captura de 1920 × 1080.",
  duplicate_cards:
    "Lectura incoherente: aparece la misma carta en Hero y board. Se conserva el último resultado confirmado.",
};

const eventLabels: Record<string, string> = {
  HOLE_CARDS_DETECTED: "Cartas de Hero detectadas",
  FLOP_DEALT: "Flop detectado",
  TURN_DEALT: "Turn detectado",
  RIVER_DEALT: "River detectado",
  BOARD_CARDS_UPDATED: "Board actualizado",
  HERO_CARDS_CLEARED: "Zona de Hero vacía",
  BOARD_CARDS_CLEARED: "Zona del board vacía",
};

function Region({
  name,
  value,
  id,
}: {
  name: string;
  value?: CardRegion;
  id: string;
}) {
  const status = value?.status || "waiting";
  const labels = {
    waiting: "Esperando imágenes",
    pending: `Confirmando lectura · ${value?.confirmations ?? 0}/${value?.required_confirmations ?? 3}`,
    confirmed: "Lectura confirmada",
    empty: "Zona vacía confirmada",
    unknown: "Lectura desconocida · Último resultado conservado",
    conflict: "Cartas incompatibles · Último resultado conservado",
  };
  return (
    <div className={`card-region ${status}`} data-testid={`${id}-region`}>
      <div className="card-region-heading">
        <h3>{name}</h3>
        <span>{labels[status]}</span>
      </div>
      <div className="recognized-cards" aria-label={`Cartas de ${name}`}>
        {value?.cards.length ? (
          value.cards.map((card) => (
            <div
              className={`recognized-card ${card.suit}`}
              key={`${card.rank}-${card.suit}`}
              data-testid={`${id}-card`}
              aria-label={cardText(card)}
            >
              <strong>
                {card.rank === "T" ? "10" : card.rank}
                <span>{suits[card.suit]}</span>
              </strong>
              <small>{Math.round(card.confidence * 100)}% similitud</small>
            </div>
          ))
        ) : (
          <span className="cards-empty">Sin cartas confirmadas</span>
        )}
      </div>
    </div>
  );
}

export function CardPanel() {
  const { capture, available } = useCapture();
  const cards = capture.observation_state.cards;
  const historyOnly = capture.state !== "running";
  return (
    <section className="panel card-panel" aria-label="Reconocimiento de cartas">
      <div className="section-heading">
        <div>
          <span className="eyebrow">LECTURA VISUAL</span>
          <h2>Cartas observadas</h2>
        </div>
        <span className="outline-badge">
          {cards?.demo
            ? "Referencias de demostración"
            : cards?.profile || "Sin perfil activo"}
        </span>
      </div>
      {cards?.demo && (
        <p className="card-notice">
          Baraja sintética Zeros demo. El reconocimiento en una sala real
          requiere sus propias referencias y calibración.
        </p>
      )}
      {!available ? (
        <p className="card-notice">
          Sin conexión con el backend. Los resultados mostrados pueden estar
          desactualizados.
        </p>
      ) : historyOnly && capture.frame ? (
        <p className="card-notice">
          Último resultado de la captura finalizada. No es una lectura en
          directo.
        </p>
      ) : capture.state === "stopped" ? (
        <p className="card-notice">
          Captura detenida. Se conserva su último resultado.
        </p>
      ) : null}
      {cards?.detector_status !== "ready" && (
        <p className="card-notice">
          {reasons[cards?.detector_status || "not_configured"] ||
            "Reconocimiento no disponible."}
        </p>
      )}
      <div className="card-regions">
        <Region name="Hero" value={cards?.hero} id="hero" />
        <Region name="Board" value={cards?.board} id="board" />
      </div>
      <p className="card-footnote">
        Se requieren 3 lecturas consecutivas. La similitud mide coincidencia
        visual con una referencia; no es una probabilidad de acierto.
      </p>
      <p className="card-footnote">
        El detector usa el layout guardado al iniciar la captura. Reinicia la
        fuente para aplicar cambios de regiones o referencias.
      </p>
      <div className="card-events-heading">
        <h3>Eventos de cartas</h3>
        <span>
          <b data-testid="card-event-count">{cards?.event_count ?? 0}</b>{" "}
          emitidos · Últimos 40
        </span>
      </div>
      <ol className="card-events" aria-label="Eventos de cartas">
        {!cards?.events.length && (
          <li className="muted">Todavía no hay cambios confirmados.</li>
        )}
        {cards?.events
          .slice()
          .reverse()
          .map((event) => (
            <li
              key={`${capture.capture_id}:${event.id}`}
              data-testid="card-event"
              data-event-type={event.type}
            >
              <time>{event.timestamp.toFixed(1)} s</time>
              <span>
                {eventLabels[event.type] || event.type}
                <small>
                  {event.cards.map(cardText).join(" · ") ||
                    "Sin cartas visibles"}
                </small>
              </span>
              <code>
                #{event.id} · f{event.frame_id}
              </code>
            </li>
          ))}
      </ol>
    </section>
  );
}
