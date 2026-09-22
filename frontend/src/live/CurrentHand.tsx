import { useState } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { handLabels } from "../hands/types";
import type { FieldEvidence } from "../game/types";

const suits: Record<string, string> = { s: "♠", h: "♥", d: "♦", c: "♣" };
const streets: Record<string, string> = {
  unknown: "Sin determinar",
  preflop: "Preflop",
  flop: "Flop",
  turn: "Turn",
  river: "River",
};

function Cards({
  codes,
  label,
  evidence,
}: {
  codes: string[];
  label: string;
  evidence?: FieldEvidence;
}) {
  return (
    <div className="current-cards">
      <span className="small-label">{label}</span>
      <div className="current-card-row" aria-label={label}>
        {codes.length ? (
          codes.map((code) => (
            <span
              className={`current-card ${"hd".includes(code[1]) ? "red" : ""}`}
              key={code}
            >
              {code[0] === "T" ? "10" : code[0]}
              <span>{suits[code[1]]}</span>
            </span>
          ))
        ) : (
          <span className="muted">Sin cartas confirmadas</span>
        )}
      </div>
      {codes.length > 0 && evidence?.status !== "confirmed" && (
        <small>Última lectura conservada</small>
      )}
    </div>
  );
}

function Amount({
  value,
  unit,
  evidence,
  id,
}: {
  value?: string | null;
  unit?: string | null;
  evidence?: FieldEvidence;
  id: string;
}) {
  return (
    <>
      <strong data-testid={id}>
        {value == null ? "—" : `${value}${unit ? ` ${unit}` : ""}`}
      </strong>
      <small>
        {value == null
          ? "Sin confirmar"
          : evidence?.status === "confirmed"
            ? "Lectura confirmada"
            : "Última lectura conservada"}
      </small>
    </>
  );
}

export function CurrentHand() {
  const { capture, available } = useCapture();
  const game = capture.observation_state.game_state;
  const [seat, setSeat] = useState(() => {
    try {
      const saved = localStorage.getItem("zeros.hero-seat") || "";
      return /^[1-6]$/.test(saved) ? saved : "";
    } catch {
      return "";
    }
  });
  const calculationSeat = capture.poker?.config.hero_seat;
  const selectedSeat = calculationSeat ? String(calculationSeat) : seat;
  const hero = game?.players.find(
    (player) => player.seat === Number(selectedSeat),
  );
  const active = game?.players.find(
    (player) => player.player_id === game.current_player,
  );
  return (
    <aside className="panel current-hand" aria-label="Mano actual">
      <div className="current-hand-heading">
        <div>
          <span className="eyebrow">TU MESA AHORA</span>
          <h2>Mano actual</h2>
        </div>
        <span className="outline-badge">
          {handLabels[game?.hand_status || "unidentified"]}
        </span>
      </div>
      <p className="current-hand-state">
        {!available
          ? "Sin actualizaciones · Estado conservado"
          : capture.state === "running"
            ? "Observación en directo"
            : "Último estado observado"}
      </p>
      <Cards
        codes={game?.hero_cards || []}
        label="Hero"
        evidence={game?.evidence.hero_cards}
      />
      <Cards
        codes={game?.board || []}
        label="Board"
        evidence={game?.evidence.board}
      />
      <div className="current-amounts">
        <div>
          <span>Bote</span>
          <Amount
            id="current-pot"
            value={game?.pot}
            unit={game?.pot_unit}
            evidence={game?.evidence.pot}
          />
        </div>
        <div>
          <span>Stack de Hero</span>
          <Amount
            id="current-hero-stack"
            value={hero?.stack}
            unit={hero?.stack_unit}
            evidence={
              hero
                ? game?.evidence[`players.${hero.seat - 1}.stack`]
                : undefined
            }
          />
        </div>
      </div>
      <label className="hero-seat">
        Asiento de Hero · asignación manual
        <select
          aria-label="Asiento de Hero"
          value={selectedSeat}
          disabled={!!calculationSeat}
          onChange={(event) => {
            setSeat(event.target.value);
            try {
              localStorage.setItem("zeros.hero-seat", event.target.value);
            } catch {
              /* In-memory selection still works. */
            }
          }}
        >
          <option value="">Sin asignar</option>
          {[1, 2, 3, 4, 5, 6].map((value) => (
            <option key={value} value={value}>
              Asiento {value}
            </option>
          ))}
        </select>
        {calculationSeat && <small>Asignado en Motor matemático.</small>}
      </label>
      <dl className="current-facts">
        <div>
          <dt>Calle</dt>
          <dd data-testid="current-street">
            {streets[game?.street || "unknown"]}
          </dd>
        </div>
        <div>
          <dt>Turno observado</dt>
          <dd>
            {active
              ? active.nickname || `Asiento ${active.seat}`
              : "Sin determinar"}
          </dd>
        </div>
      </dl>
      {capture.observation_state.hands?.active_hand?.partial_start && (
        <p className="card-notice">
          Inicio parcial: la mano ya podía estar en curso.
        </p>
      )}
      <p className="card-footnote">
        Observaciones de la mesa. Los valores pueden confirmarse en momentos
        distintos.
      </p>
    </aside>
  );
}
