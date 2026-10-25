import { ExplanationPanel } from "../explanations/ExplanationPanel";
import { useEffect, useState } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";
import type { DecisionDetail } from "./types";
import { EvaluationReview } from "./EvaluationReview";

export function DecisionPanel() {
  const { capture, available } = useCapture();
  const decisions = capture.decisions;
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setSelected(null);
    setDetail(null);
  }, [capture.capture_id, capture.server_id]);
  useEffect(() => {
    setDetail(null);
    setError(null);
    if (!selected || !available || decisions?.visibility !== "training") return;
    const controller = new AbortController();
    fetch(`/api/decisions/${selected}`, { signal: controller.signal })
      .then(readResponse)
      .then((record) => {
        if (!controller.signal.aborted) setDetail(record as DecisionDetail);
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "No se pudo recuperar la decisión.",
          );
      });
    return () => controller.abort();
  }, [
    selected,
    available,
    decisions?.visibility,
    capture.capture_id,
    capture.server_id,
  ]);
  return (
    <section
      className="panel poker-panel decision-panel"
      aria-label="Decisiones de Hero"
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">INFORMACIÓN EN ESE INSTANTE</span>
          <h2>Decisiones de Hero</h2>
        </div>
        <span className="outline-badge">{decisions?.count ?? 0} guardadas</span>
      </div>
      <p>
        Se conserva una instantánea por turno confirmado de Hero. Las cartas,
        importes, rangos y estadísticas posteriores no reescriben ese momento.
      </p>
      {decisions?.storage_error && (
        <p role="alert">{decisions.storage_error}</p>
      )}
      {decisions?.visibility !== "training" ? (
        <p className="card-notice">
          Las instantáneas se archivan en privado. Abre una mano guardada para
          revisarlas cuando se cumpla la política de cierre de esa captura.
        </p>
      ) : (
        <>
          <p>
            {available
              ? decisions.reason
              : "Sin conexión con el estado actual."}
          </p>
          {available && (
            <ul className="decision-list">
              {[...decisions.recent].reverse().map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setSelected(item.id)}
                    aria-pressed={selected === item.id}
                  >
                    Ver decisión · {item.street} · {item.timestamp.toFixed(1)} s
                  </button>
                  <span>
                    Hero {item.hero_seat} · {item.action_count} acciones previas
                    {item.id === decisions.active_id ? " · Turno actual" : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {error && <p role="alert">{error}</p>}
          {selected && !detail && !error && available && (
            <p role="status">Cargando instantánea…</p>
          )}
          {detail && available && (
            <article className="decision-detail" data-testid="decision-detail">
              <h3>Momento guardado · {detail.timestamp.toFixed(1)} s</h3>
              <p>
                Hero: {detail.request.state.hero_cards.join(" ")} · Board:{" "}
                {detail.request.state.board.join(" ") || "Preflop"}
              </p>
              <p>
                Bote: {detail.request.state.pot}{" "}
                {detail.request.state.pot_unit ?? ""} · Evento de corte{" "}
                {detail.source_event_sequence} · Fotograma {detail.frame_id}
              </p>
              <p>
                {detail.history_complete
                  ? "Historial observado desde el inicio de la mano."
                  : "Historial parcial: faltan acciones anteriores; no se han reconstruido a posteriori."}
              </p>
              {!detail.strategy_input_available && (
                <p>
                  Sin modelo completo de rangos en ese instante. Se conservan
                  los supuestos configurados y los datos conocidos.
                </p>
              )}
              <details>
                <summary>Stacks y apuestas guardados</summary>
                <ul>
                  {detail.request.state.players.map((p) => (
                    <li key={p.seat}>
                      Asiento {p.seat}: stack {p.stack ?? "—"} · apuesta{" "}
                      {p.current_bet ?? "—"}
                      {p.folded ? " · retirado" : ""}
                    </li>
                  ))}
                </ul>
              </details>
              <details>
                <summary>Acciones anteriores ({detail.actions.length})</summary>
                <ol>
                  {detail.actions.map((a) => (
                    <li key={a.sequence}>
                      {a.timestamp.toFixed(1)} s ·{" "}
                      {a.type.replace("PLAYER_", "")} ·{" "}
                      {a.player_id?.split(":").at(-1)}
                      {a.amount ? ` · total ${a.amount}` : ""}
                    </li>
                  ))}
                </ol>
              </details>
              {detail.request.decision && (
                <details>
                  <summary>Rangos y estadísticas utilizados</summary>
                  <ul>
                    {detail.request.decision.exploit_pools.map(
                      ([seat, pool]) => (
                        <li key={seat}>
                          Asiento {seat}: {pool.length} combos ponderados
                          guardados
                        </li>
                      ),
                    )}
                  </ul>
                  {detail.request.decision.counts.map(([seat, counts]) => (
                    <p key={seat}>
                      Asiento {seat}:{" "}
                      {counts
                        .map(([stat, hits, n]) => `${stat} ${hits}/${n}`)
                        .join(" · ")}
                    </p>
                  ))}
                  <p>
                    Estas muestras se fijaron al inicio de la mano. El JSON
                    incluye también las estadísticas observadas hasta el punto
                    de decisión.
                  </p>
                </details>
              )}
              <a
                href={`/api/decisions/${detail.id}`}
                target="_blank"
                rel="noreferrer"
              >
                Ver JSON completo de la instantánea
              </a>
              <EvaluationReview key={detail.id} identity={detail.id} />
              <ExplanationPanel
                key={`explanation:${detail.id}`}
                identity={detail.id}
              />
            </article>
          )}
        </>
      )}
    </section>
  );
}
