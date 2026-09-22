import { useLive } from "../live/LiveProvider";

const labels = {
  "system.ready": "Conexión establecida",
  "system.pong": "Respuesta de conexión recibida",
  "system.error": "Mensaje rechazado por el servidor",
};

export function EventLog({ compact = false }: { compact?: boolean }) {
  const { events } = useLive();
  const visible = compact ? events.slice(0, 4) : events;
  return (
    <div className="event-log" aria-label="Mensajes de conexión">
      {visible.length === 0 && (
        <p className="muted log-empty">Esperando conexión con el servidor…</p>
      )}
      {visible.map((event) => (
        <div
          className="event-row"
          key={`${event.connection_id}:${event.sequence}`}
        >
          <span className="event-dot" />
          <time dateTime={event.timestamp}>
            {new Date(event.timestamp).toLocaleTimeString("es-ES")}
          </time>
          <span>{labels[event.type]}</span>
          <code>#{event.sequence}</code>
        </div>
      ))}
    </div>
  );
}
