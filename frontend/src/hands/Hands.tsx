import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { readResponse } from "../capture/types";
import { handLabels, type HandSummary } from "./types";
import type { GameState } from "../game/types";
import type { PokerEvent } from "../events/types";
import { eventLabels } from "../events/PokerEvents";
import { HandReview } from "../feedback/HandReview";
import { useCapture } from "../capture/CaptureProvider";

export function Hands() {
  const [query] = useSearchParams();
  const scope = query.get("scope_id");
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<{
    items: HandSummary[];
    total: number;
  } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    setData(null);
    fetch(
      `/api/hands?offset=${offset}${scope ? `&scope_id=${encodeURIComponent(scope)}` : ""}`,
      { signal: controller.signal },
    )
      .then(readResponse<{ items: HandSummary[]; total: number }>)
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") setError(true);
      });
    return () => controller.abort();
  }, [scope, offset, attempt]);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ARCHIVO DE OBSERVACIONES</span>
          <h1>Manos guardadas</h1>
          <p>Manos y eventos conservados, incluidos los tramos incompletos.</p>
        </div>
      </div>
      {scope && (
        <Link to="/hands" className="text-link" onClick={() => setOffset(0)}>
          Ver todas las capturas
        </Link>
      )}
      <button
        className="button secondary"
        onClick={() => setAttempt(attempt + 1)}
      >
        Actualizar manos
      </button>
      {error ? (
        <p role="alert">
          No se pudieron cargar las manos. Comprueba el servidor y vuelve a
          actualizar.
        </p>
      ) : !data ? (
        <p>Consultando manos…</p>
      ) : (
        <section className="panel hand-panel">
          <p>
            {data.total} manos guardadas{scope ? " en esta captura" : ""}.
          </p>
          {data.items.length === 0 ? (
            <p>Todavía no hay manos para mostrar.</p>
          ) : (
            <ul className="saved-hands">
              {data.items.map((hand) => (
                <li key={hand.hand_id}>
                  <Link to={`/hands/${hand.hand_id}`}>
                    Mano {hand.number} · {handLabels[hand.status]}
                  </Link>
                  <small>
                    {hand.context?.name || "Captura"} · Desde{" "}
                    {hand.started_timestamp.toFixed(1)} s
                    {hand.partial_start ? " · Inicio parcial" : ""}
                  </small>
                </li>
              ))}
            </ul>
          )}
          <div className="hand-pagination">
            <button
              className="button secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Anteriores
            </button>
            <button
              className="button secondary"
              disabled={offset + 20 >= data.total}
              onClick={() => setOffset(offset + 20)}
            >
              Siguientes
            </button>
          </div>
        </section>
      )}
    </>
  );
}

type Detail = {
  hand: HandSummary & { state: GameState };
  events: PokerEvent[];
  has_more: boolean;
  next_after: number;
};

export function HandDetail() {
  const { id } = useParams();
  const { capture } = useCapture();
  const [after, setAfter] = useState(0);
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    fetch(`/api/hands/${encodeURIComponent(id || "")}?after=${after}`, {
      signal: controller.signal,
    })
      .then(readResponse<Detail>)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [
    id,
    after,
    capture.server_id,
    capture.feedback?.revision,
    capture.feedback?.review_blocked,
  ]);
  return (
    <>
      <Link className="text-link" to="/hands">
        ← Manos guardadas
      </Link>
      <div className="page-heading">
        <h1>Detalle de mano</h1>
      </div>
      {error ? (
        <p role="alert">{error}</p>
      ) : !data ? (
        <p>Consultando mano…</p>
      ) : (
        <section className="panel hand-panel">
          <h2>
            Mano {data.hand.number} · {handLabels[data.hand.status]}
          </h2>
          <p>
            {data.hand.partial_start ? "Inicio parcial. " : ""}
            {data.hand.status === "incomplete"
              ? "La observación terminó sin confirmar el final de la mano."
              : "Límite identificado mediante señales visuales confirmadas."}
          </p>
          <dl className="game-summary">
            <div>
              <dt>Hero</dt>
              <dd>{data.hand.state.hero_cards.join(" · ") || "—"}</dd>
            </div>
            <div>
              <dt>Último board observado</dt>
              <dd>{data.hand.state.board.join(" · ") || "—"}</dd>
            </div>
            <div>
              <dt>Último bote observado</dt>
              <dd>
                {data.hand.state.pot ?? "—"} {data.hand.state.pot_unit}
              </dd>
            </div>
          </dl>
          <h3>Eventos guardados</h3>
          <ol className="poker-event-list">
            {data.events.map((event) => (
              <li key={event.sequence}>
                #{event.sequence} · {event.timestamp.toFixed(1)} s ·{" "}
                {eventLabels[event.type] || event.type}
                {event.player_id && (
                  <small>
                    Asiento{" "}
                    {data.hand.state.players.find(
                      (p) => p.player_id === event.player_id,
                    )?.seat ?? "—"}
                    {event.amount !== null
                      ? ` · Apuesta total ${event.amount} ${event.unit || ""}`
                      : ""}
                    {event.confidence !== null
                      ? ` · Confianza ${Math.round(event.confidence * 100)}%`
                      : ""}
                  </small>
                )}
                {!!event.action_evidence?.length && (
                  <small>
                    Turno visual y etiqueta corroborados con stack, apuesta y
                    bote.
                  </small>
                )}
              </li>
            ))}
          </ol>
          <div className="hand-pagination">
            <button
              className="button secondary"
              disabled={after === 0}
              onClick={() => setAfter(0)}
            >
              Primeros eventos
            </button>
            <button
              className="button secondary"
              disabled={!data.has_more}
              onClick={() => setAfter(data.next_after)}
            >
              Más eventos
            </button>
          </div>
          <p className="card-footnote">
            Historial observado: puede faltar el inicio o acciones sin señales
            suficientes. La apuesta indicada es el total de la calle, no el
            incremento pagado. La confianza no es una probabilidad calibrada.
          </p>
        </section>
      )}
      {data && id && <HandReview key={id} handId={id} />}
    </>
  );
}
