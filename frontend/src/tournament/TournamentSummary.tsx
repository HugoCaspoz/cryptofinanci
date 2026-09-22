import type { TournamentSummary as Summary } from "./types";
import { formats } from "./types";

export function TournamentSummary({ tournament }: { tournament: Summary }) {
  return (
    <div className="tournament-summary" aria-label="Torneo confirmado">
      <h3>Torneo confirmado para esta mano</h3>
      <p>
        {formats[tournament.tournament_type]} · Buy-in {tournament.buy_in}{" "}
        {tournament.currency} · Stack inicial {tournament.starting_stack} fichas
      </p>
      <p>
        {tournament.players} participantes ·{" "}
        {tournament.remaining_players ?? "Sin confirmar"} restantes
      </p>
      <p>
        {tournament.prize_pool === null
          ? "Premios sin confirmar"
          : `${tournament.paid_places} puestos premiados · Total ${tournament.prize_pool} ${tournament.currency}`}
      </p>
      {tournament.prize_structure && (
        <ul>
          {tournament.prize_structure.map((p) => (
            <li key={p.first_place}>
              Puestos {p.first_place}–{p.last_place}: {p.amount}{" "}
              {tournament.currency} por jugador
            </li>
          ))}
        </ul>
      )}
      <p>
        {tournament.population_prior
          ? `Prior de torneo: ${tournament.population_prior.label} · Fuerza ${tournament.population_prior.strength} oportunidades.`
          : "Se mantiene el prior genérico; el buy-in no ajusta automáticamente el rango."}
      </p>
      <p className="card-footnote">
        Contexto fijado al confirmar el inicio. No calcula ICM ni convierte
        fichas en dinero.
      </p>
    </div>
  );
}
