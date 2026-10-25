import "./sessions.css";
import { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";

type Session = {
  scope_id: string;
  status: string;
  created_at?: string;
  hands?: number;
};
type Decision = {
  id: string;
  hand_id: string;
  street: string;
  action: string;
  ev_loss_bb: number;
  history_complete: boolean;
};
type Stat = { value: number | null; hits: number; opportunities: number };
type Summary = {
  hands_observed: number;
  hands_incomplete: number;
  decisions: number;
  comparable: number;
  not_comparable: number;
  ev_loss_bb: number | null;
  opponents_total: number;
  top_costs: Decision[];
  best_decisions: Decision[];
  missed_bluffs: Decision[];
  costly_aggression: Decision[];
  leaks: { label: string; count: number; ev_loss_bb: number }[];
  hero_statistics: {
    hands_played: number | null;
    hero_identified_hands: number;
    vpip: Stat;
    pfr: Stat;
    three_bet: Stat;
    reason: string;
  };
  opponents: {
    id: string;
    nickname?: string;
    seat?: number;
    stats?: Record<string, Stat>;
  }[];
};

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="panel empty-state">
      <h2>{title}</h2>
      <p>{description}</p>
      <Link className="button primary" to="/live">
        Ir al panel en directo
      </Link>
    </div>
  );
}

export function Sessions() {
  const { capture, available } = useCapture();
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<{ items: Session[]; total: number } | null>(
    null,
  );
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(false);
    if (!available) return () => controller.abort();
    fetch(`/api/sessions?offset=${offset}`, { signal: controller.signal })
      .then(readResponse<{ items: Session[]; total: number }>)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, [
    offset,
    attempt,
    capture.server_id,
    capture.feedback?.revision,
    available,
  ]);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">CADA MANO CUENTA</span>
          <h1>Tus sesiones</h1>
          <p>Vuelve a tus decisiones y consulta su cobertura.</p>
        </div>
      </div>
      {error ? (
        <div role="alert" className="panel session-panel">
          <p>No se pudieron cargar las sesiones.</p>
          <button
            className="button secondary"
            onClick={() => setAttempt((v) => v + 1)}
          >
            Reintentar
          </button>
        </div>
      ) : !data ? (
        <p role="status">Consultando sesiones…</p>
      ) : data.total === 0 ? (
        <EmptyState
          title="Tu historia todavía está por escribir."
          description="Las sesiones aparecerán al iniciar una captura."
        />
      ) : (
        <section className="panel session-panel">
          {data.items.map((item) => (
            <p key={item.scope_id}>
              <Link to={`/session/${encodeURIComponent(item.scope_id)}`}>
                Sesión{" "}
                {item.created_at
                  ? new Date(item.created_at).toLocaleString()
                  : item.scope_id}
              </Link>{" "}
              · {item.status} · {item.hands} manos
            </p>
          ))}
          <p>{data.total} sesiones</p>
          <button
            className="button secondary"
            disabled={offset === 0}
            onClick={() => setOffset((v) => Math.max(0, v - 20))}
          >
            Anteriores
          </button>{" "}
          <button
            className="button secondary"
            disabled={offset + 20 >= data.total}
            onClick={() => setOffset((v) => v + 20)}
          >
            Siguientes
          </button>
        </section>
      )}
    </>
  );
}

function DecisionList({ title, items }: { title: string; items: Decision[] }) {
  return (
    <section className="panel session-panel">
      <h2>{title}</h2>
      {items.length ? (
        <ol>
          {items.map((item) => (
            <li key={item.id}>
              <Link
                to={`/hands/${encodeURIComponent(item.hand_id)}?decision=${encodeURIComponent(item.id)}`}
              >
                {item.street} · {item.action} · {item.ev_loss_bb.toFixed(2)} BB
              </Link>
              {!item.history_complete && " · historial parcial"}
            </li>
          ))}
        </ol>
      ) : (
        <p>Sin decisiones comparables en esta categoría.</p>
      )}
    </section>
  );
}

function percent(value: Stat) {
  return value.value === null
    ? "No disponible"
    : `${(value.value * 100).toFixed(1)}% (${value.hits}/${value.opportunities})`;
}

function SessionOpponents({
  id,
  initial,
  total,
}: {
  id: string;
  initial: Summary["opponents"];
  total: number;
}) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{
    offset: number;
    items: Summary["opponents"];
  }>({ offset: 0, items: initial });
  const [error, setError] = useState("");
  useEffect(() => {
    if (offset === 0) {
      setPage({ offset: 0, items: initial });
      return;
    }
    const controller = new AbortController();
    setError("");
    fetch(
      `/api/sessions/${encodeURIComponent(id)}/opponents?offset=${offset}`,
      { signal: controller.signal },
    )
      .then(readResponse<{ items: Summary["opponents"] }>)
      .then((data) => {
        if (!controller.signal.aborted) setPage({ offset, items: data.items });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      });
    return () => controller.abort();
  }, [id, offset, initial]);
  return (
    <>
      {error && <p role="alert">{error}</p>}
      {page.offset !== offset ? (
        <p role="status">Cargando perfiles...</p>
      ) : page.items.length ? (
        page.items.map((item) => (
          <p key={item.id}>
            {item.nickname ?? item.id} · Asiento {item.seat ?? "?"}
            {item.stats?.vpip && ` · VPIP ${percent(item.stats.vpip)}`}
          </p>
        ))
      ) : (
        <p>Sin perfiles archivados.</p>
      )}
      <p>
        {total} perfiles{" "}
        <button
          className="button secondary"
          disabled={offset === 0}
          onClick={() => setOffset((v) => Math.max(0, v - 20))}
        >
          Anteriores perfiles
        </button>{" "}
        <button
          className="button secondary"
          disabled={offset + 20 >= total}
          onClick={() => setOffset((v) => v + 20)}
        >
          Siguientes perfiles
        </button>
      </p>
    </>
  );
}

export function SessionDetail() {
  const { id } = useParams();
  const { capture, available } = useCapture();
  const [attempt, setAttempt] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const [deleteConfirmed, setDeleteConfirmed] = useState(false);
  const blocked = !available || capture.feedback?.review_blocked !== false;
  const key = JSON.stringify([
    id,
    capture.server_id,
    capture.capture_id,
    capture.feedback?.revision,
    capture.evaluations?.revision,
    blocked,
    attempt,
  ]);
  const [response, setResponse] = useState<{
    key: string;
    data?: {
      session: Session;
      allowed: boolean;
      summary: Summary | null;
      reason: string;
      partial: boolean;
    };
    error?: string;
  } | null>(null);
  useEffect(() => {
    setConfirmed(false);
    setDeleteConfirmed(false);
    if (!available) return;
    const controller = new AbortController();
    fetch(`/api/sessions/${encodeURIComponent(id ?? "")}`, {
      signal: controller.signal,
    })
      .then(
        readResponse<{
          session: Session;
          allowed: boolean;
          summary: Summary | null;
          reason: string;
          partial: boolean;
        }>,
      )
      .then((data) => {
        if (!controller.signal.aborted) setResponse({ key, data });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setResponse({ key, error: error.message });
      });
    return () => controller.abort();
  }, [id, key, available]);
  const current = response?.key === key ? response : null;
  const data = current?.data;
  const summary = !blocked && data?.allowed ? data.summary : null;
  async function finish() {
    if (!confirmed || !id) return;
    setBusy(true);
    try {
      await fetch(`/api/feedback/sessions/${encodeURIComponent(id)}/finish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_finished: true }),
      }).then(readResponse);
      setAttempt((v) => v + 1);
    } catch (error) {
      setResponse({
        key,
        error: error instanceof Error ? error.message : "No se pudo finalizar.",
      });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Link className="text-link back-link" to="/sessions">
        ← Volver a sesiones
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">REVISIÓN DE SESIÓN</span>
          <h1>Detalle de sesión</h1>
        </div>
      </div>
      {current?.error ? (
        <div className="panel session-panel" role="alert">
          <h2>{current.error}</h2>
          <button
            className="button secondary"
            onClick={() => setAttempt((v) => v + 1)}
          >
            Reintentar
          </button>
        </div>
      ) : !available ? (
        <p role="status">Conecta con el servidor para revisar la sesión.</p>
      ) : !data ? (
        <p role="status">Consultando sesión…</p>
      ) : !summary ? (
        <section className="panel session-panel">
          <h2>Resumen protegido</h2>
          <p>{data.reason}</p>
          {!blocked &&
            ["stopped", "interrupted"].includes(data.session.status) && (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />{" "}
                  Confirmo que he terminado esta sesión de juego.
                </label>
                <p>
                  <button
                    className="button primary"
                    disabled={!confirmed || busy}
                    onClick={finish}
                  >
                    Finalizar sesión y revisar
                  </button>
                </p>
              </>
            )}
        </section>
      ) : (
        <>
          {data.partial && (
            <p role="status">
              Sesión detenida o interrumpida: resumen parcial.
            </p>
          )}
          <section className="panel session-panel">
            <h2>Conservar y gestionar la sesión</h2>
            <a
              className="button secondary"
              href={`/api/sessions/${encodeURIComponent(id ?? "")}/export`}
            >
              Descargar archivo de sesión
            </a>
            <p>
              El archivo contiene datos e imágenes privados. Guárdalo antes de
              borrar una sesión.
            </p>
            {data.session.status === "finished" && (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={deleteConfirmed}
                    onChange={(e) => setDeleteConfirmed(e.target.checked)}
                  />{" "}
                  Confirmo que quiero eliminar definitivamente esta sesión y sus
                  imágenes.
                </label>
                <button
                  className="button stop-button"
                  disabled={
                    !deleteConfirmed || busy || capture.state === "running"
                  }
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await fetch(
                        `/api/sessions/${encodeURIComponent(id ?? "")}`,
                        {
                          method: "DELETE",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ confirm_scope: id }),
                        },
                      ).then(readResponse);
                      navigate("/sessions");
                    } catch (error) {
                      setResponse({
                        key,
                        error:
                          error instanceof Error
                            ? error.message
                            : "No se pudo eliminar.",
                      });
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Eliminar sesión
                </button>
              </>
            )}
          </section>
          <section className="panel session-panel">
            <h2>Resumen y cobertura</h2>
            <p>
              Manos observadas: {summary.hands_observed} · Incompletas:{" "}
              {summary.hands_incomplete}
            </p>
            <p>
              Manos con cartas de Hero:{" "}
              {summary.hero_statistics.hands_played ?? "No disponible"} · Hero
              identificado: {summary.hero_statistics.hero_identified_hands}/
              {summary.hands_observed}
            </p>
            <p>
              VPIP: {percent(summary.hero_statistics.vpip)} · PFR:{" "}
              {percent(summary.hero_statistics.pfr)} · 3-bet:{" "}
              {percent(summary.hero_statistics.three_bet)}
            </p>
            <p>{summary.hero_statistics.reason}</p>
            <p>
              EV estimada no capturada:{" "}
              {summary.ev_loss_bb === null
                ? "No disponible"
                : `${summary.ev_loss_bb.toFixed(2)} BB`}{" "}
              · {summary.comparable}/{summary.decisions} decisiones comparables.
            </p>
            <p>
              Diferencia positiva acumulada frente a la mejor opción del menú
              del modelo base. No representa una pérdida monetaria real. Las
              decisiones sin EV comparable se excluyen ({summary.not_comparable}
              ).
            </p>
          </section>
          <DecisionList
            title="TOP 10 decisiones más costosas"
            items={summary.top_costs}
          />
          <DecisionList
            title="Decisiones con menor diferencia de EV"
            items={summary.best_decisions}
          />
          <DecisionList
            title="Oportunidades de farol no tomadas según el modelo"
            items={summary.missed_bluffs}
          />
          <DecisionList
            title="Agresiones costosas con equity baja"
            items={summary.costly_aggression}
          />
          <p>
            La equity baja es una aproximación para revisar posibles faroles; no
            identifica la intención del jugador.
          </p>
          <section className="panel session-panel">
            <h2>Principales fugas según el modelo</h2>
            {summary.leaks.length ? (
              summary.leaks.map((item) => (
                <p key={item.label}>
                  {item.label} · {item.count} decisiones ·{" "}
                  {item.ev_loss_bb.toFixed(2)} BB
                </p>
              ))
            ) : (
              <p>Sin pérdidas comparables.</p>
            )}
          </section>
          <section className="panel session-panel">
            <h2>Perfiles rivales</h2>
            <SessionOpponents
              key={key}
              id={id ?? ""}
              initial={summary.opponents}
              total={summary.opponents_total}
            />
            <Link to={`/hands?scope_id=${encodeURIComponent(id ?? "")}`}>
              Ver manos de esta sesión
            </Link>
          </section>
        </>
      )}
    </>
  );
}

export function NotFound() {
  return (
    <EmptyState
      title="Esta página no está en la mesa."
      description="La dirección no existe. Puedes volver al panel en directo para continuar."
    />
  );
}
