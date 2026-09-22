import { Link } from "react-router";
import { Icon } from "../components/Icon";
import { EventLog } from "../components/EventLog";
import { useLive } from "../live/LiveProvider";

export function Dashboard() {
  const { status, latency, mode } = useLive();
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">TU ESPACIO DE ANÁLISIS</span>
          <h1>Todo empieza en la mesa.</h1>
          <p>
            Observa cada mano. Encuentra una nueva perspectiva sobre tu juego.
          </p>
        </div>
        <span className="phase-badge">
          FASE 22 <span>/ 30</span>
        </span>
      </div>
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="pill">
            <span /> TU FUENTE, EN DIRECTO
          </span>
          <h2>
            Una conexión.
            <br />
            Muchas posibilidades.
          </h2>
          <p>
            Conecta un archivo de vídeo o comparte una ventana. Observa en
            directo las imágenes que llegan a tu espacio de análisis.
          </p>
          <Link className="button primary" to="/live">
            Abrir panel en directo <Icon name="arrow" size={18} />
          </Link>
          <span className="hero-caption">
            Archivo, pantalla o ventana · 5 FPS por defecto
          </span>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="art-table">
            <div className="table-line" />
            <span className="table-wordmark">zeros.</span>
            <span className="table-subtitle">POKER LAB</span>
          </div>
          <span className="art-chip chip-one" />
          <span className="art-chip chip-two" />
          <span className="art-chip chip-three" />
          <span className="art-label">UN NUEVO PUNTO DE VISTA ↗</span>
        </div>
      </section>
      <section className="metric-grid" aria-label="Estado del proyecto">
        <article className="metric">
          <span>
            <Icon name="activity" />
            Conexión en directo
          </span>
          <strong className={status === "connected" ? "green" : ""}>
            {status === "connected" ? "Activa" : "Conectando"}
          </strong>
          <small>Comunicación con el servidor</small>
        </article>
        <article className="metric">
          <span>
            <Icon name="live" />
            Latencia de conexión
          </span>
          <strong>
            {latency ?? "—"} <em>ms</em>
          </strong>
          <small>Ida y vuelta del WebSocket</small>
        </article>
        <article className="metric">
          <span>
            <Icon name="sessions" />
            Sesiones guardadas
          </span>
          <strong>—</strong>
          <small>Almacenamiento pendiente</small>
        </article>
        <article className="metric">
          <span>
            <Icon name="shield" />
            Modo del servidor
          </span>
          <strong className="mode-value">
            {mode === "LIVE_REAL_MONEY"
              ? "Dinero real"
              : mode === "TRAINING"
                ? "Entrenamiento"
                : "—"}
          </strong>
          <small>
            {mode === "LIVE_REAL_MONEY"
              ? "Revisión estratégica diferida"
              : mode === "TRAINING"
                ? "Entorno de práctica"
                : "Esperando al servidor"}
          </small>
        </article>
      </section>
      <div className="dashboard-bottom">
        <section className="panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">EN TIEMPO REAL</span>
              <h2>Actividad del sistema</h2>
            </div>
            <Link className="text-link" to="/live">
              Ver conexión <Icon name="arrow" size={16} />
            </Link>
          </div>
          <EventLog compact />
          <div className="panel-footnote">
            Mensajes de conexión · Consulta las manos observadas en su archivo
          </div>
        </section>
        <section className="panel next-panel">
          <span className="step-number">23</span>
          <span className="eyebrow">EL SIGUIENTE PASO</span>
          <h2>Volver al momento de decidir.</h2>
          <p>
            La próxima fase organizará las decisiones en una línea temporal,
            vinculadas al fotograma y al estado de cada momento.
          </p>
          <div className="next-tag">
            <Icon name="live" size={16} /> Timeline de decisiones{" "}
            <span>PRÓXIMAMENTE</span>
          </div>
        </section>
      </div>
    </>
  );
}
