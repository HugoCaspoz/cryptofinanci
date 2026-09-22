import type { PostflopAnalysis as Analysis } from "./types";

export const labels: Record<string, string> = {
  high_card: "Carta alta",
  pair: "Pareja",
  two_pair: "Doble pareja",
  three_of_a_kind: "Trío",
  straight: "Escalera",
  flush: "Color",
  full_house: "Full",
  four_of_a_kind: "Póker",
  straight_flush: "Escalera de color",
  set: "Set (pareja en mano)",
  trips: "Trips (pareja en el board)",
  board_trips: "Trío en el board",
  overpair: "Overpair",
  underpair: "Underpair",
  pocket_pair: "Pareja en mano",
  board_pair: "Pareja en el board",
  top_pair: "Top pair",
  middle_pair: "Pareja intermedia",
  bottom_pair: "Pareja baja",
  open_ended: "Escalera abierta",
  double_gutshot: "Doble gutshot",
  gutshot: "Gutshot",
  one_ended: "Escalera a una punta",
  unpaired: "Sin parejas",
  paired: "Emparejado",
  quads: "Póker",
  coordinated: "Coordinado",
  semi_coordinated: "Semicoordinado",
  dry: "Seco",
  in_position: "Último en actuar",
  out_of_position: "Primero en actuar",
  between: "Posición intermedia",
  hero: "Hero",
  opponent: "Rival",
  equal: "Igual",
  undetermined: "Sin ventaja concluyente",
};
const label = (key: string) => labels[key] ?? key;
const pct = (n: number) => `${(n * 100).toFixed(1)} %`;

export function PostflopAnalysis({ analysis }: { analysis: Analysis }) {
  const {
    hand_strength: hand,
    draws,
    board_texture: board,
    position,
    bet_sizing: sizing,
    range_comparison: ranges,
  } = analysis;
  return (
    <section aria-label="Análisis postflop" className="postflop-analysis">
      <h3>Análisis postflop</h3>
      <div className="poker-metrics">
        <div>
          <span>Mano formada</span>
          <strong data-testid="postflop-hand">{label(hand.category)}</strong>
          <small>
            {label(hand.detail)}
            {hand.plays_board ? " · Juega el board" : ""}
          </small>
        </div>
        <div>
          <span>Textura del board</span>
          <strong>{label(board.texture)}</strong>
          <small>
            {board.pairing === "trips"
              ? "Trío en el board"
              : label(board.pairing)}{" "}
            · Palos {board.suit_pattern.join("–")} · Alta {board.high_card}
          </small>
        </div>
        <div>
          <span>Posición postflop</span>
          <strong data-testid="postflop-position">
            {position ? label(position.relative) : "Sin confirmar"}
          </strong>
          {position && (
            <small>
              Orden por asientos: {position.action_order.join(" → ")}
            </small>
          )}
        </div>
      </div>
      <h4>Proyectos</h4>
      {draws.flush && <p>Proyecto de color: {draws.flush.count} cartas.</p>}
      {draws.straight && (
        <p>
          {label(draws.straight.kind)}: {draws.straight.count} cartas.
        </p>
      )}
      <p data-testid="postflop-draws">
        {draws.completion_count
          ? `${draws.completion_count} cartas distintas completan color o escalera: ${draws.completion_cards.join(", ")}.`
          : "Sin proyectos de color o escalera a una carta."}
      </p>
      {!!draws.backdoor_flush_suits.length && (
        <p>Color backdoor: necesita turn y river favorables.</p>
      )}
      {draws.backdoor_straight && (
        <p>Escalera backdoor: necesita turn y river favorables.</p>
      )}
      <p className="card-footnote">
        Las cartas de mejora no garantizan ganar ni descuentan cartas ocultas
        del rival. En river no hay proyectos. La textura es una clasificación
        descriptiva.
      </p>
      <h4>Tamaños observados</h4>
      {sizing ? (
        <>
          <p>
            Bote al inicio de la calle: {sizing.street_start_pot} {sizing.unit}.
            Contribuciones totales de la calle:
          </p>
          <ul>
            {sizing.by_seat.map((p) => (
              <li key={p.seat}>
                Asiento {p.seat}: {p.amount} ({pct(p.pot_fraction)} del bote
                inicial).
              </li>
            ))}
          </ul>
          {!sizing.by_seat.length && <p>Aún no hay apuestas.</p>}
        </>
      ) : (
        <p>
          Se necesitan un bote y todas las apuestas confirmados en la misma
          unidad.
        </p>
      )}
      <p className="card-footnote">
        Estos porcentajes describen contribuciones acumuladas; no son el tamaño
        de la última apuesta ni una recomendación. Equity y SPR de la mano se
        muestran arriba.
      </p>
      <h4>Comparación de rangos</h4>
      {ranges ? (
        <>
          <div className="poker-metrics">
            <div>
              <span>Equity del rango de Hero</span>
              <strong data-testid="range-equity">
                {pct(ranges.hero_equity)}
              </strong>
              <small>Ventaja de rango: {label(ranges.range_advantage)}</small>
            </div>
            <div>
              <span>Nuts actuales · Hero / rival</span>
              <strong>
                {pct(ranges.hero.current_nuts_fraction)} /{" "}
                {pct(ranges.opponent.current_nuts_fraction)}
              </strong>
              <small>
                Ventaja por densidad de nuts:{" "}
                {label(ranges.nut_advantage_proxy)}
              </small>
            </div>
          </div>
          <p>
            {ranges.method === "exact_river_joint"
              ? `${ranges.samples} repartos enumerados.`
              : `${ranges.samples} simulaciones · Intervalo del 95 %: ${pct(ranges.interval_95[0])} – ${pct(ranges.interval_95[1])}.`}{" "}
            Combos compatibles con el board: {ranges.hero.available_combos} /{" "}
            {ranges.opponent.available_combos}.
          </p>
          <p className="card-footnote">
            Se comparan los rangos completos frente a un rival, bloqueados solo
            por el board; las cartas concretas de Hero no se fijan. El intervalo
            mide solo el muestreo. Nuts = mejor mano posible ahora; su densidad
            se calcula por rango y es un indicador limitado, no una solución GTO
            ni una predicción de apuestas.
          </p>
        </>
      ) : (
        <p>
          Confirma un rango de Hero para esta mano y un único rival para
          comparar rangos.
        </p>
      )}
      {!!analysis.warnings.length && (
        <ul>
          {analysis.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
