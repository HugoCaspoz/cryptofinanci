import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Icon } from "../components/Icon";
import { EventLog } from "../components/EventLog";
import { useLive } from "../live/LiveProvider";

export function Dashboard() {
  const { status, latency, mode } = useLive();
  const [total, setTotal] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/sessions", { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then((data) => {
        if (!controller.signal.aborted) setTotal(data.total);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [status]);
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
          FASE 30 <span>/ 30</span>
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
            Archivo, pantalla o ventana · Muestreo inteligente 2/10 FPS
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
          <strong>{total ?? "—"}</strong>
          <small>
            <Link to="/sessions">Abrir archivo de sesiones</Link>
          </small>
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
          <span className="step-number">30</span>
          <span className="eyebrow">REVISIÓN DE SESIÓN</span>
          <h2>Revisar la sesión completa.</h2>
          <p>
            Consulta la cobertura, las diferencias de EV y las decisiones
            archivadas de cada sesión.
          </p>
          <div className="next-tag">
            <Icon name="live" size={16} /> Dashboard final{" "}
            <Link to="/sessions">Ver sesiones</Link>
          </div>
        </section>
      </div>
    </>
  );
}
