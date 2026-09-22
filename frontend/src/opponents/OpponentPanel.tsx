import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";
import { AdaptiveRangeView } from "./AdaptiveRangeView";
import { TournamentFields } from "../tournament/TournamentFields";
import { TournamentSummary } from "../tournament/TournamentSummary";
import type { TournamentContext } from "../tournament/types";

const rates = [
  ["vpip", "VPIP"],
  ["pfr", "PFR"],
  ["three_bet", "3Bet"],
  ["fold_to_three_bet", "Fold to 3Bet"],
  ["cbet", "CBet flop"],
  ["fold_to_cbet", "Fold to CBet"],
  ["wtsd", "WTSD"],
] as const;
const levels: Record<string, string> = {
  none: "Sin muestra",
  low: "Baja",
  medium: "Media",
  high: "Alta",
};
const pct = (n: number | null) =>
  n === null ? "—" : `${(100 * n).toFixed(1)} %`;

export function OpponentPanel() {
  const { capture, available } = useCapture();
  const game = capture.observation_state.game_state;
  const model = capture.opponents;
  const analysis = available ? model?.analysis : null;
  const observations = available ? model?.observations : null;
  const [seats, setSeats] = useState([1, 2, 3, 4, 5, 6]);
  const [button, setButton] = useState(6);
  const [confirmed, setConfirmed] = useState(false);
  const [priors, setPriors] = useState<Record<number, string>>({});
  const [priorStrength, setPriorStrength] = useState(30);
  const [tournament, setTournament] = useState<TournamentContext | null>(null);
  const savedTournament = analysis?.context
    ? JSON.stringify(analysis.context.tournament ?? null)
    : undefined;
  useEffect(() => {
    if (savedTournament !== undefined)
      setTournament(JSON.parse(savedTournament));
  }, [savedTournament, capture.server_id]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setConfirmed(false);
    setError(null);
  }, [game?.hand_id, capture.capture_id, capture.server_id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await readResponse(
        await fetch("/api/opponents/context", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            capture_id: capture.capture_id,
            hand_id: game?.hand_id,
            state_revision: game?.revision,
            seats,
            button_seat: button,
            start_confirmed: confirmed,
            prior_strength: priorStrength,
            tournament,
            range_priors: seats.map((seat) => ({
              seat,
              range: priors[seat] || "random",
            })),
          }),
          signal: AbortSignal.timeout(10000),
        }),
      );
      setConfirmed(false);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudo confirmar el inicio.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function showdown(hand_id: string) {
    setBusy(true);
    setError(null);
    try {
      await readResponse(
        await fetch("/api/opponents/showdown", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            capture_id: capture.capture_id,
            hand_id,
            showdown_observed: true,
          }),
          signal: AbortSignal.timeout(10000),
        }),
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudo guardar el showdown.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel opponent-panel" aria-label="Modelo de rivales">
      <div className="section-heading">
        <div>
          <span className="eyebrow">ACCIONES OBSERVADAS</span>
          <h2>Modelo de rivales</h2>
        </div>
        <span className="outline-badge">
          {model?.visibility === "training"
            ? "Entrenamiento"
            : "Cálculo interno"}
        </span>
      </div>
      <div className="opponent-body">
        <p>
          Confirma los asientos que recibieron cartas y el botón antes de la
          primera acción. El inicio debe mostrar solo SB y BB, sin antes. Repite
          la confirmación en cada mano.
        </p>
        <form onSubmit={submit}>
          <fieldset>
            <legend>Participantes para estadísticas</legend>
            <div className="opponent-seats">
              {[1, 2, 3, 4, 5, 6].map((seat) => (
                <label key={seat}>
                  <input
                    type="checkbox"
                    aria-label={`Estadísticas asiento ${seat}`}
                    checked={seats.includes(seat)}
                    onChange={(e) =>
                      setSeats(
                        e.target.checked
                          ? [...seats, seat].sort()
                          : seats.filter((s) => s !== seat),
                      )
                    }
                  />{" "}
                  Asiento {seat}
                </label>
              ))}
            </div>
          </fieldset>
          <label>
            Botón para estadísticas{" "}
            <select
              aria-label="Botón para estadísticas"
              value={button}
              onChange={(e) => setButton(Number(e.target.value))}
            >
              {[1, 2, 3, 4, 5, 6].map((s) => (
                <option key={s} value={s}>
                  Asiento {s}
                </option>
              ))}
            </select>
          </label>
          <TournamentFields
            value={tournament}
            onChange={(value) => {
              setTournament(value);
              setConfirmed(false);
            }}
          />
          <label className="opponent-confirm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            Confirmo participantes e inicio sin acciones previas
          </label>
          <details>
            <summary>Supuestos de los rangos adaptativos</summary>
            <p>
              Se fijan al inicio de cada mano. random incluye cualquier mano;
              admite AA, AKs, AKo y combos con pesos como AA:0.5,KK.
            </p>
            <label>
              Fuerza del prior genérico (oportunidades equivalentes)
              <input
                type="number"
                min={1}
                max={1000}
                required
                value={priorStrength}
                onChange={(e) => setPriorStrength(Number(e.target.value))}
              />
            </label>
            {seats.map((seat) => (
              <label key={seat}>
                Rango inicial asiento {seat}
                <input
                  value={priors[seat] || ""}
                  placeholder="random"
                  maxLength={4096}
                  onChange={(e) =>
                    setPriors({ ...priors, [seat]: e.target.value })
                  }
                />
              </label>
            ))}
          </details>
          <button
            className="button secondary"
            disabled={
              !available ||
              busy ||
              !confirmed ||
              capture.state !== "running" ||
              game?.street !== "preflop" ||
              !game?.hand_id ||
              analysis?.context?.hand_id === game?.hand_id
            }
          >
            Confirmar inicio para estadísticas
          </button>
        </form>
        {error && <p role="alert">{error}</p>}
        {model?.storage_error && <p role="alert">{model.storage_error}</p>}
        {model?.visibility !== "training" ? (
          <>
            <p className="card-notice">
              Estadísticas de acciones observadas. Los rangos y el análisis
              estratégico permanecen privados durante la mano.
            </p>
            {observations && (
              <div
                className="opponent-profiles"
                data-testid="observed-statistics"
              >
                {observations.profiles
                  .filter((p) => p.active)
                  .map((player) => (
                    <article className="opponent-card" key={player.id}>
                      <h3>{player.nickname || `Asiento ${player.seat}`}</h3>
                      <p>
                        {player.hands} manos · {player.actions} acciones
                        observadas
                      </p>
                      <dl>
                        {rates.map(([key, name]) => (
                          <div key={key}>
                            <dt>{name}</dt>
                            <dd>
                              {pct(player.stats[key].value)}
                              <small>
                                {player.stats[key].hits} /{" "}
                                {player.stats[key].opportunities} oportunidades
                              </small>
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </article>
                  ))}
                <p>
                  {observations.coverage} «—» indica ausencia de muestra; estos
                  datos no predicen la siguiente acción.
                </p>
              </div>
            )}
          </>
        ) : (
          <>
            {!available && (
              <p>
                Sin conexión: estadísticas ocultas hasta recuperar las
                actualizaciones.
              </p>
            )}
            {analysis && (
              <>
                <p role="status">{analysis.coverage}</p>
                {analysis.adaptive?.tournament && (
                  <TournamentSummary
                    tournament={analysis.adaptive.tournament}
                  />
                )}
                <p className="card-footnote">
                  Perfiles separados por asiento y captura. Un cambio de nombre
                  inicia otro perfil; verifica la identidad si se reemplaza un
                  jugador sin cambiar su nombre visible.
                </p>
                <div className="opponent-profiles">
                  {analysis.profiles
                    .filter((p) => p.active)
                    .map((player) => (
                      <article
                        key={player.id}
                        className="opponent-card"
                        aria-label={`Perfil asiento ${player.seat}`}
                      >
                        <h3>
                          {player.nickname || `Asiento ${player.seat}`}{" "}
                          <small>Asiento {player.seat}</small>
                        </h3>
                        <p>
                          Manos observadas: {player.hands} · Acciones:{" "}
                          <span data-testid={`opponent-actions-${player.seat}`}>
                            {player.actions}
                          </span>
                        </p>
                        <dl>
                          {rates.map(([key, name]) => {
                            const rate = player.stats[key];
                            return (
                              <div key={key}>
                                <dt>{name}</dt>
                                <dd>
                                  <strong
                                    data-testid={`opponent-${key}-${player.seat}`}
                                  >
                                    {pct(rate.value)}
                                  </strong>
                                  <small>
                                    {rate.hits} / {rate.opportunities}{" "}
                                    oportunidades · Confianza{" "}
                                    {levels[rate.confidence]}
                                  </small>
                                  {rate.interval_95 && (
                                    <small>
                                      IC 95 %: {pct(rate.interval_95[0])} –{" "}
                                      {pct(rate.interval_95[1])}
                                    </small>
                                  )}
                                </dd>
                              </div>
                            );
                          })}
                          <div>
                            <dt>AF postflop</dt>
                            <dd>
                              <strong>
                                {player.stats.aggression_factor.value?.toFixed(
                                  2,
                                ) ?? "—"}
                              </strong>
                              <small>
                                {
                                  player.stats.aggression_factor
                                    .aggressive_actions
                                }{" "}
                                bets/subidas /{" "}
                                {player.stats.aggression_factor.calls} calls
                                {!player.stats.aggression_factor.calls
                                  ? " · Sin denominador"
                                  : ""}
                              </small>
                            </dd>
                          </div>
                        </dl>
                        {analysis.adaptive?.ranges
                          .filter((r) => r.seat === player.seat)
                          .map((range) => (
                            <AdaptiveRangeView key={range.seat} range={range} />
                          ))}
                      </article>
                    ))}
                </div>
                {!analysis.profiles.length && (
                  <p>Inicia una fuente para observar jugadores.</p>
                )}
                {!!analysis.pending_showdowns.length && (
                  <div className="opponent-outcomes">
                    <h3>Showdowns pendientes</h3>
                    <p>
                      Solo confirma si viste llegar al showdown a todos los
                      asientos indicados. Ver el river por sí solo no basta.
                    </p>
                    {analysis.pending_showdowns.map((h) => (
                      <div key={h.hand_id}>
                        <p>
                          Mano {h.hand_id.slice(0, 8)} · Asientos{" "}
                          {h.seats.join(", ")}
                        </p>
                        <button
                          className="button secondary"
                          disabled={busy}
                          onClick={() => showdown(h.hand_id)}
                        >
                          Confirmar showdown observado
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <p className="card-footnote">
                  Rangos heurísticos sin calibrar. Las estadísticas anteriores
                  se fijan al inicio: con pocas oportunidades pesa más el prior,
                  con más datos pesa más el rival. Los pesos no representan
                  certeza sobre sus cartas. El ajuste no contempla tamaños de
                  apuesta, posición ni proyectos postflop. Puedes usar estos
                  rangos en el motor matemático seleccionando «Adaptativos».
                </p>
                <p className="card-footnote">
                  VPIP/PFR se consolidan al cerrar un preflop completo. 3Bet,
                  Fold to 3Bet del agresor inicial y CBet de flop usan
                  oportunidades resueltas; AF utiliza acciones postflop
                  confirmadas. Datos incompletos o all-in suspenden las métricas
                  contextuales de esa mano. WTSD requiere un final por folds o
                  showdown confirmado. «—» significa que faltan oportunidades,
                  nunca 0 %.
                </p>
                <p className="card-footnote">
                  Confianza por tamaño de muestra: baja con menos de 30
                  oportunidades, media de 30 a 99 y alta desde 100. El intervalo
                  describe incertidumbre de muestreo; no garantiza identidad,
                  cobertura del vídeo ni estabilidad del rival. Actualizado
                  hasta el evento {analysis.event_sequence} (
                  {analysis.timestamp.toFixed(1)} s).
                </p>
              </>
            )}
          </>
        )}
      </div>
    </section>
  );
}
