import { Icon } from "../components/Icon";
import { Connection } from "../components/Connection";
import { EventLog } from "../components/EventLog";
import { useLive } from "../live/LiveProvider";
import { useCapture } from "../capture/CaptureProvider";
import { CaptureControls } from "../capture/CaptureControls";
import { Preview } from "../capture/Preview";
import { PipelineDebug } from "../capture/PipelineDebug";
import { LayoutPanel } from "../table/LayoutPanel";
import { useTableLayout } from "../table/useTableLayout";
import { CardPanel } from "../cards/CardPanel";
import { OcrPanel } from "../ocr/OcrPanel";
import { GameStatePanel } from "../game/GameStatePanel";
import { PokerEvents } from "../events/PokerEvents";
import { HandPanel } from "../hands/HandPanel";
import { CurrentHand } from "../live/CurrentHand";
import { PokerPanel } from "../poker/PokerPanel";
import { PreflopPanel } from "../preflop/PreflopPanel";
import { OpponentPanel } from "../opponents/OpponentPanel";
import { StrategyPanel } from "../strategy/StrategyPanel";
import { DecisionPanel } from "../decisions/DecisionPanel";
import { FeedbackPanel } from "../feedback/FeedbackPanel";

export function Live() {
  const { mode, latency, ping, status } = useLive();
  const { capture, available } = useCapture();
  const editor = useTableLayout();
  const stateLabel = {
    idle: "Sin fuente",
    running: "Capturando",
    ended: "Vídeo finalizado",
    stopped: "Captura detenida",
    error: "Captura interrumpida",
  }[capture.state];
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">MANTÉN EL FOCO</span>
          <h1>En directo</h1>
          <p>El punto de encuentro entre tu mesa y tu análisis.</p>
        </div>
        <span className="outline-badge">{stateLabel}</span>
      </div>
      <CaptureControls />
      <FeedbackPanel />
      {!available && (
        <p className="live-stale" role="alert">
          Actualizaciones interrumpidas. Se conserva el último estado mientras
          vuelve la conexión.
        </p>
      )}
      <div className="live-grid live-table-grid">
        <section className="panel video-panel">
          <div className="section-heading">
            <h2>Vista de la mesa</h2>
            <span className="muted capture-source-name">
              {capture.name || "Sin fuente"}
            </span>
          </div>
          <Preview editor={editor} />
          <div className="video-footer">
            <span>
              <i /> {stateLabel}
            </span>
            <span>
              {capture.frame
                ? `${capture.capture_fps} FPS objetivo · ${capture.frame.width} × ${capture.frame.height}`
                : "— FPS · — × —"}
            </span>
          </div>
        </section>
        <CurrentHand />
      </div>
      <PokerEvents />
      <HandPanel />
      <PokerPanel />
      <PreflopPanel />
      <OpponentPanel />
      <StrategyPanel />
      <DecisionPanel />
      <h2 className="live-tools-heading">
        Lecturas y configuración de la mesa
      </h2>
      <LayoutPanel editor={editor} />
      <CardPanel />
      <GameStatePanel />
      <OcrPanel />
      <PipelineDebug />
      <section className="panel connection-panel live-connection">
        <span className="eyebrow">ESTADO DEL SISTEMA</span>
        <h2>
          {status === "connected" ? "Todo conectado." : "Conectando contigo."}
        </h2>
        <Connection />
        <dl>
          <div>
            <dt>Modo</dt>
            <dd>
              {mode === "TRAINING"
                ? "Entrenamiento"
                : mode === "LIVE_REAL_MONEY"
                  ? "Dinero real"
                  : "Pendiente"}
            </dd>
          </div>
          <div>
            <dt>Latencia WebSocket</dt>
            <dd>{latency === null ? "—" : `${latency} ms`}</dd>
          </div>
          <div>
            <dt>Fuente de vídeo</dt>
            <dd>
              {capture.source === "file"
                ? "Archivo de vídeo"
                : capture.source === "screen"
                  ? "Pantalla / ventana"
                  : "Pendiente"}
            </dd>
          </div>
          <div>
            <dt>Frame recibido</dt>
            <dd data-testid="frame-id">{capture.frame?.frame_id ?? "—"}</dd>
          </div>
          <div>
            <dt>Tiempo de fuente</dt>
            <dd>
              {capture.frame ? `${capture.frame.timestamp.toFixed(1)} s` : "—"}
            </dd>
          </div>
        </dl>
        <button
          className="button secondary"
          onClick={ping}
          disabled={status !== "connected"}
        >
          <Icon name="activity" size={17} />
          Comprobar conexión
        </button>
        <div className="mode-note">
          <Icon name="shield" size={20} />
          <p>
            {mode === "LIVE_REAL_MONEY"
              ? "En dinero real, el análisis estratégico se reserva para después de la mano o sesión."
              : mode === "TRAINING"
                ? "En entrenamiento, la estrategia baseline y explotativa se muestra en cada decisión de Hero."
                : "El servidor confirmará el modo al conectar."}{" "}
            <span>
              Estrategia preflop, postflop heads-up y ajustes por rivales
              disponibles en entrenamiento.
            </span>
          </p>
        </div>
      </section>
      <section className="panel live-events">
        <div className="section-heading">
          <div>
            <span className="eyebrow">CONEXIÓN EN DIRECTO</span>
            <h2>Registro de actividad</h2>
          </div>
          <span className="muted">Últimos 40 mensajes</span>
        </div>
        <EventLog />
      </section>
    </>
  );
}
