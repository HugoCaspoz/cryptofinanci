import { useCapture } from "../capture/CaptureProvider";
import type { FieldEvidence } from "./types";

const streets = {
  unknown: "Sin determinar",
  preflop: "Preflop",
  flop: "Flop",
  turn: "Turn",
  river: "River",
};
const suits: Record<string, string> = { s: "♠", h: "♥", d: "♦", c: "♣" };
const cardsText = (codes: string[]) =>
  codes
    .map((c) => `${c[0] === "T" ? "10" : c[0]}${suits[c[1]] || ""}`)
    .join(" · ") || "—";
const amount = (value: string | null, unit: string | null) =>
  value === null ? "—" : `${value}${unit ? ` ${unit}` : ""}`;
const renderValue = (value: unknown): string =>
  value == null
    ? "—"
    : Array.isArray(value)
      ? value.join(" · ") || "—"
      : String(value);

function Reading({
  value,
  evidence,
  id,
}: {
  value: string;
  evidence?: FieldEvidence;
  id?: string;
}) {
  const confirmed =
    evidence?.status === "confirmed" || evidence?.status === "empty";
  return (
    <span className="game-reading">
      <strong data-testid={id}>{value}</strong>
      <small className={confirmed ? "" : "game-uncertain"}>
        {evidence?.confirmed_timestamp == null
          ? "Sin confirmar"
          : `${confirmed ? "Confirmado" : "Último valor · sin confirmar ahora"} · ${evidence.confirmed_timestamp.toFixed(1)} s`}
      </small>
    </span>
  );
}

function fieldName(field: string) {
  const labels: Record<string, string> = {
    pot: "Bote",
    pot_unit: "Unidad del bote",
    street: "Calle",
    board: "Board",
    hero_cards: "Hero",
    small_blind: "Ciega pequeña",
    big_blind: "Ciega grande",
    blinds_unit: "Unidad de ciegas",
    nickname: "Nombre",
    stack: "Stack",
    current_bet: "Apuesta",
    stack_unit: "Unidad del stack",
    bet_unit: "Unidad de apuesta",
  };
  const match = /^players\.(\d+)\.(.+)$/.exec(field);
  return match
    ? `Asiento ${Number(match[1]) + 1} · ${labels[match[2]] || match[2]}`
    : labels[field] || field;
}

export function GameStatePanel() {
  const { capture, available } = useCapture();
  const state = capture.observation_state.game_state;
  return (
    <section className="panel game-panel" aria-label="Estado de la partida">
      <div className="section-heading">
        <div>
          <span className="eyebrow">MESA OBSERVADA</span>
          <h2>Estado de la partida</h2>
        </div>
        <span className="outline-badge">Revisión {state?.revision ?? 0}</span>
      </div>
      <p className="card-footnote">
        Últimos valores confirmados de cada zona. Pueden proceder de momentos
        distintos. Las acciones requieren señales adicionales concordantes.
      </p>
      {!available ? (
        <p className="card-notice">
          Sin conexión. Este estado puede estar desactualizado.
        </p>
      ) : capture.state !== "running" && state?.frame_id != null ? (
        <p className="card-notice">
          Estado conservado de la captura terminada o detenida.
        </p>
      ) : null}
      {!state || state.frame_id === null ? (
        <p>Esperando observaciones de la mesa.</p>
      ) : (
        <>
          <dl className="game-summary">
            <div>
              <dt>Calle observada</dt>
              <dd data-testid="game-street">{streets[state.street]}</dd>
              <small>Según las últimas cartas confirmadas</small>
            </div>
            <div>
              <dt>Bote</dt>
              <dd>
                <Reading
                  id="game-pot"
                  value={amount(state.pot, state.pot_unit)}
                  evidence={state.evidence.pot}
                />
              </dd>
            </div>
            <div>
              <dt>Ciegas</dt>
              <dd>
                <Reading
                  id="game-blinds"
                  value={`${amount(state.small_blind, state.blinds_unit)} / ${amount(state.big_blind, state.blinds_unit)}`}
                  evidence={state.evidence.small_blind}
                />
              </dd>
            </div>
            <div>
              <dt>Hero</dt>
              <dd>
                <Reading
                  id="game-hero"
                  value={cardsText(state.hero_cards)}
                  evidence={state.evidence.hero_cards}
                />
              </dd>
            </div>
            <div>
              <dt>Board</dt>
              <dd>
                <Reading
                  id="game-board"
                  value={cardsText(state.board)}
                  evidence={state.evidence.board}
                />
              </dd>
            </div>
          </dl>
          <div className="game-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Asiento</th>
                  <th>Nombre</th>
                  <th>Stack</th>
                  <th>Apuesta</th>
                  <th>Posición / Acción</th>
                </tr>
              </thead>
              <tbody>
                {state.players.map((player, index) => (
                  <tr key={player.player_id}>
                    <td>{player.seat}</td>
                    <td>
                      <Reading
                        value={player.nickname ?? "—"}
                        evidence={state.evidence[`players.${index}.nickname`]}
                      />
                    </td>
                    <td>
                      <Reading
                        id={`game-stack-${player.seat}`}
                        value={amount(player.stack, player.stack_unit)}
                        evidence={state.evidence[`players.${index}.stack`]}
                      />
                    </td>
                    <td>
                      <Reading
                        id={`game-bet-${player.seat}`}
                        value={amount(player.current_bet, player.bet_unit)}
                        evidence={
                          state.evidence[`players.${index}.current_bet`]
                        }
                      />
                    </td>
                    <td>
                      {player.folded
                        ? "Fold confirmado"
                        : player.all_in
                          ? "All-in confirmado"
                          : state.current_player === player.player_id
                            ? "Turno observado"
                            : "Sin determinar"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="card-footnote">
            Botón sin determinar. El turno requiere un indicador visual
            reconocido. Los asientos no identifican personas entre capturas.
          </p>
          <details className="game-history">
            <summary>Cambios confirmados ({state.revision})</summary>
            <p className="card-footnote">
              Últimas 40 revisiones · Cada cambio compara valores confirmados.
              No representa una acción de póker.
            </p>
            <ol>
              {[...state.events].reverse().map((event) => (
                <li key={event.id}>
                  <strong>
                    Revisión {event.revision} · {event.timestamp.toFixed(1)} s
                  </strong>
                  <ul>
                    {event.changes.map((change) => (
                      <li key={change.field}>
                        {fieldName(change.field)}:{" "}
                        {renderValue(change.previous)} →{" "}
                        {renderValue(change.current)}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </details>
        </>
      )}
    </section>
  );
}
