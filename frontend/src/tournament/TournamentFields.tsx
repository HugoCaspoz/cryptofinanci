import { useEffect, useState } from "react";
import { formats } from "./types";
import type { TournamentContext, TournamentPrior } from "./types";

const initial: TournamentContext = {
  buy_in: "",
  currency: "EUR",
  tournament_type: "mtt",
  starting_stack: 5000,
  players: 6,
  remaining_players: null,
  prize_structure: null,
  population_prior: null,
};

export function TournamentFields({
  value,
  onChange,
}: {
  value: TournamentContext | null;
  onChange: (value: TournamentContext | null) => void;
}) {
  const [draft, setDraft] = useState<TournamentContext>(initial);
  useEffect(() => {
    if (value) setDraft(value);
  }, [value]);
  function update(change: Partial<TournamentContext>) {
    const next = { ...draft, ...change };
    setDraft(next);
    onChange(next);
  }
  function updatePrior(change: Partial<TournamentPrior>) {
    if (draft.population_prior)
      update({ population_prior: { ...draft.population_prior, ...change } });
  }
  return (
    <fieldset className="tournament-fields">
      <legend>Contexto del torneo</legend>
      <label>
        <input
          type="checkbox"
          checked={value !== null}
          onChange={(e) => onChange(e.target.checked ? draft : null)}
        />
        Añadir contexto de torneo a esta mano
      </label>
      {value && (
        <>
          <p>
            Revisa estos datos antes de cada confirmación. El buy-in es el coste
            de entrada en dinero; el stack está en fichas. Los premios se
            introducen en la misma moneda, sin bounties.
          </p>
          <div className="tournament-grid">
            <label>
              Buy-in
              <input
                type="number"
                min="0"
                max="1000000000"
                step="0.01"
                required
                value={draft.buy_in}
                onChange={(e) => update({ buy_in: e.target.value })}
              />
            </label>
            <label>
              Moneda del torneo
              <select
                value={draft.currency}
                onChange={(e) => update({ currency: e.target.value })}
              >
                {["EUR", "USD", "GBP", "CAD", "AUD", "CHF", "JPY"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label>
              Tipo de torneo
              <select
                value={draft.tournament_type}
                onChange={(e) =>
                  update({
                    tournament_type: e.target
                      .value as TournamentContext["tournament_type"],
                  })
                }
              >
                {Object.entries(formats).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Stack inicial (fichas)
              <input
                type="number"
                min={1}
                max={1000000000}
                step={1}
                required
                value={draft.starting_stack}
                onChange={(e) =>
                  update({ starting_stack: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Participantes totales
              <input
                type="number"
                min={2}
                max={1000000}
                step={1}
                required
                value={draft.players}
                onChange={(e) => update({ players: Number(e.target.value) })}
              />
            </label>
            <label>
              Jugadores restantes (opcional)
              <input
                type="number"
                min={2}
                max={draft.players}
                step={1}
                value={draft.remaining_players ?? ""}
                onChange={(e) =>
                  update({
                    remaining_players:
                      e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <label>
            <input
              type="checkbox"
              checked={draft.prize_structure !== null}
              onChange={(e) =>
                update({
                  prize_structure: e.target.checked
                    ? [{ first_place: 1, last_place: 1, amount: "" }]
                    : null,
                })
              }
            />
            Conozco la estructura completa de premios
          </label>
          {draft.prize_structure && (
            <>
              <p>
                Incluye todos los puestos premiados desde el primero, sin
                huecos. Cada tramo indica el premio por jugador.
              </p>
              {draft.prize_structure.map((tier, index) => (
                <div className="tournament-grid prize-tier" key={index}>
                  <label>
                    Desde puesto {index + 1}
                    <input
                      type="number"
                      min={1}
                      max={draft.players}
                      step={1}
                      required
                      value={tier.first_place}
                      onChange={(e) =>
                        update({
                          prize_structure: draft.prize_structure!.map((p, i) =>
                            i === index
                              ? { ...p, first_place: Number(e.target.value) }
                              : p,
                          ),
                        })
                      }
                    />
                  </label>
                  <label>
                    Hasta puesto {index + 1}
                    <input
                      type="number"
                      min={tier.first_place}
                      max={draft.players}
                      step={1}
                      required
                      value={tier.last_place}
                      onChange={(e) =>
                        update({
                          prize_structure: draft.prize_structure!.map((p, i) =>
                            i === index
                              ? { ...p, last_place: Number(e.target.value) }
                              : p,
                          ),
                        })
                      }
                    />
                  </label>
                  <label>
                    Premio por puesto {index + 1}
                    <input
                      type="number"
                      min="0.01"
                      max="1000000000"
                      step="0.01"
                      required
                      value={tier.amount}
                      onChange={(e) =>
                        update({
                          prize_structure: draft.prize_structure!.map((p, i) =>
                            i === index ? { ...p, amount: e.target.value } : p,
                          ),
                        })
                      }
                    />
                  </label>
                </div>
              ))}
              <div className="tournament-buttons">
                <button
                  type="button"
                  className="button secondary"
                  disabled={
                    draft.prize_structure.length >= 1000 ||
                    draft.prize_structure.at(-1)!.last_place >= draft.players
                  }
                  onClick={() => {
                    const next = draft.prize_structure!.at(-1)!.last_place + 1;
                    update({
                      prize_structure: [
                        ...draft.prize_structure!,
                        { first_place: next, last_place: next, amount: "" },
                      ],
                    });
                  }}
                >
                  Añadir tramo de premios
                </button>
                <button
                  type="button"
                  className="button secondary"
                  disabled={draft.prize_structure.length <= 1}
                  onClick={() =>
                    update({
                      prize_structure: draft.prize_structure!.slice(0, -1),
                    })
                  }
                >
                  Quitar último tramo
                </button>
              </div>
            </>
          )}
          <label>
            <input
              type="checkbox"
              checked={draft.population_prior !== null}
              onChange={(e) =>
                update({
                  population_prior: e.target.checked
                    ? {
                        label: "Supuesto de estudio",
                        strength: 10,
                        vpip: 0.28,
                        pfr: 0.18,
                        three_bet: 0.07,
                      }
                    : null,
                })
              }
            />
            Usar un prior de población para este torneo
          </label>
          {draft.population_prior && (
            <>
              <p>
                Hipótesis manual para este buy-in, moneda y formato. El precio
                de entrada no demuestra el nivel del rival. Sin activarla se
                mantiene el prior genérico.
              </p>
              <div className="tournament-grid">
                <label>
                  Nombre del supuesto
                  <input
                    required
                    maxLength={80}
                    value={draft.population_prior.label}
                    onChange={(e) => updatePrior({ label: e.target.value })}
                  />
                </label>
                <label>
                  Fuerza del prior de torneo
                  <input
                    type="number"
                    min={1}
                    max={30}
                    step={1}
                    required
                    value={draft.population_prior.strength}
                    onChange={(e) =>
                      updatePrior({ strength: Number(e.target.value) })
                    }
                  />
                </label>
                {(
                  [
                    ["vpip", "VPIP"],
                    ["pfr", "PFR"],
                    ["three_bet", "3Bet"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    Prior {label} del torneo (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="0.1"
                      required
                      value={Number(
                        (draft.population_prior![key] * 100).toFixed(1),
                      )}
                      onChange={(e) =>
                        updatePrior({ [key]: Number(e.target.value) / 100 })
                      }
                    />
                  </label>
                ))}
              </div>
              <p className="card-footnote">
                La fuerza equivale a oportunidades previas (máximo 30). Con más
                oportunidades confirmadas que esa fuerza, los datos del rival
                pesan más que el prior. Solo afecta a VPIP, PFR y 3Bet, nunca
                modifica las cartas ni el stack observado.
              </p>
            </>
          )}
        </>
      )}
    </fieldset>
  );
}
