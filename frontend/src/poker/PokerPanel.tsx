import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";
import type { PokerConfig } from "./types";
import { PostflopAnalysis } from "./PostflopAnalysis";

const initial: PokerConfig = {
  hero_seat: null,
  opponents: [],
  pot_includes_bets: null,
  samples: 1000,
  seed: 42,
};
const percent = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(1)} %`;
const money = (value: string | null | undefined, unit?: string | null) =>
  value == null ? "—" : `${value}${unit ? ` ${unit}` : ""}`;

export function PokerPanel() {
  const { capture, available } = useCapture();
  const poker = capture.poker;
  const saved = JSON.stringify(poker?.config || initial);
  const [draft, setDraft] = useState<PokerConfig>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handId = capture.observation_state.game_state?.hand_id;
  const [contextConfirmed, setContextConfirmed] = useState(false);
  useEffect(() => {
    setDraft(JSON.parse(saved));
    setError(null);
  }, [saved, capture.capture_id, capture.server_id]);
  useEffect(() => {
    setContextConfirmed(false);
  }, [handId, capture.capture_id, capture.server_id]);
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await readResponse(
        await fetch("/api/poker/config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...draft,
            capture_id: capture.capture_id,
            postflop_context:
              contextConfirmed && handId && draft.postflop_context
                ? { ...draft.postflop_context, hand_id: handId }
                : null,
          }),
          signal: AbortSignal.timeout(10000),
        }),
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudo aplicar la configuración.",
      );
    } finally {
      setBusy(false);
    }
  }
  const analysis = available ? poker?.analysis : null;
  const metrics = analysis?.metrics;
  const equity = analysis?.equity;
  return (
    <section className="panel poker-panel" aria-label="Motor matemático">
      <div className="section-heading">
        <div>
          <span className="eyebrow">ESTUDIO DE LA MANO</span>
          <h2>Motor matemático</h2>
        </div>
        <span className="outline-badge">
          {poker?.visibility === "training"
            ? "Entrenamiento"
            : "Cálculo interno"}
        </span>
      </div>
      <p>
        Confirma los participantes y cómo muestra el bote tu mesa. Los rangos
        son supuestos de estudio: puedes fijarlos o adaptarlos a acciones y
        estadísticas confirmadas.
      </p>
      <form onSubmit={save}>
        <div className="poker-settings">
          <label>
            Origen de los rangos
            <select
              aria-label="Origen de los rangos"
              value={draft.range_source ?? "manual"}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  range_source: e.target.value as "manual" | "adaptive",
                })
              }
            >
              <option value="manual">Manuales</option>
              <option value="adaptive">Adaptativos · modelo de rivales</option>
            </select>
          </label>
          <label>
            Hero para cálculos
            <select
              aria-label="Hero para cálculos"
              value={draft.hero_seat || ""}
              onChange={(e) => {
                const seat = Number(e.target.value) || null;
                setDraft({
                  ...draft,
                  hero_seat: seat,
                  opponents: seat
                    ? draft.opponents.filter((p) => p.seat !== seat)
                    : [],
                });
              }}
            >
              <option value="">Sin asignar</option>
              {[1, 2, 3, 4, 5, 6].map((seat) => (
                <option key={seat} value={seat}>
                  Asiento {seat}
                </option>
              ))}
            </select>
          </label>
          <label>
            Bote observado
            <select
              aria-label="Bote observado"
              value={
                draft.pot_includes_bets === null
                  ? "unknown"
                  : String(draft.pot_includes_bets)
              }
              onChange={(e) =>
                setDraft({
                  ...draft,
                  pot_includes_bets:
                    e.target.value === "unknown"
                      ? null
                      : e.target.value === "true",
                })
              }
            >
              <option value="unknown">Sin confirmar</option>
              <option value="true">Incluye las apuestas de la calle</option>
              <option value="false">No incluye las apuestas de la calle</option>
            </select>
          </label>
        </div>
        <fieldset>
          <legend>Rivales que participan en la mano</legend>
          <p>
            Incluye todos los rivales activos. Los folds confirmados se excluyen
            del cálculo. Revisa esta selección en cada mano.
          </p>
          {[1, 2, 3, 4, 5, 6]
            .filter((seat) => seat !== draft.hero_seat)
            .map((seat) => {
              const selected = draft.opponents.find((p) => p.seat === seat);
              return (
                <div className="poker-range" key={seat}>
                  <label>
                    <input
                      type="checkbox"
                      aria-label={`Incluir asiento ${seat}`}
                      checked={!!selected}
                      disabled={!draft.hero_seat}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          opponents: e.target.checked
                            ? [...draft.opponents, { seat, range: "random" }]
                            : draft.opponents.filter((p) => p.seat !== seat),
                        })
                      }
                    />{" "}
                    Asiento {seat}
                  </label>
                  {selected && (
                    <input
                      aria-label={`Rango del asiento ${seat}`}
                      value={selected.range}
                      maxLength={4096}
                      placeholder="random o AA,KK,AKs"
                      disabled={draft.range_source === "adaptive"}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          opponents: draft.opponents.map((p) =>
                            p.seat === seat
                              ? { ...p, range: e.target.value }
                              : p,
                          ),
                        })
                      }
                    />
                  )}
                </div>
              );
            })}
          <small>
            {draft.range_source === "adaptive" &&
              "Usa los priors y el historial del Modelo de rivales; confirma allí el inicio de cada mano. Los campos manuales no se usan. "}
            random = cualquier mano. Ejemplos: AA, AKs, AKo, AsKh. Peso opcional
            por combo: AA:0.5,KK. Sin rangos con + ni intervalos.
          </small>
        </fieldset>
        <fieldset>
          <legend>Contexto postflop opcional · mano actual</legend>
          <p>
            Los asientos deben estar numerados en sentido horario. Revisa
            rangos, participantes y botón en cada mano.
          </p>
          <div className="poker-settings">
            <label>
              Rango de Hero para comparar
              <input
                aria-label="Rango de Hero para comparar"
                value={draft.postflop_context?.hero_range ?? ""}
                maxLength={4096}
                placeholder="AA,KK,AKs"
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    postflop_context: {
                      hand_id: handId ?? "",
                      button_seat: draft.postflop_context?.button_seat ?? null,
                      hero_range: e.target.value || null,
                    },
                  })
                }
              />
            </label>
            <label>
              Botón postflop
              <select
                aria-label="Botón postflop"
                value={draft.postflop_context?.button_seat ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    postflop_context: {
                      hand_id: handId ?? "",
                      hero_range: draft.postflop_context?.hero_range ?? null,
                      button_seat: Number(e.target.value) || null,
                    },
                  })
                }
              >
                <option value="">Sin confirmar</option>
                {[1, 2, 3, 4, 5, 6].map((seat) => (
                  <option key={seat} value={seat}>
                    Asiento {seat}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            <input
              type="checkbox"
              checked={contextConfirmed}
              disabled={!handId}
              onChange={(e) => setContextConfirmed(e.target.checked)}
            />{" "}
            Confirmo el contexto postflop para esta mano
          </label>
          <small>
            Sin esta confirmación se calculan mano, proyectos, textura, equity y
            SPR; no se aplica el rango de Hero ni el botón.
          </small>
        </fieldset>
        <button
          className="button secondary"
          disabled={busy || !available || !capture.capture_id}
        >
          {busy ? "Aplicando…" : "Aplicar cálculo"}
        </button>
        {!capture.capture_id && (
          <small>Inicia una fuente para configurar el cálculo.</small>
        )}
        {error && <p role="alert">{error}</p>}
      </form>
      {poker?.visibility !== "training" ? (
        <p className="card-notice">
          En dinero real los resultados se calculan internamente. No se muestran
          durante la captura; la revisión posterior se incorporará en otra fase.
        </p>
      ) : (
        <>
          {!available && (
            <p className="card-notice">
              Sin actualizaciones: el análisis se oculta hasta recuperar la
              conexión.
            </p>
          )}
          {poker.status === "unconfigured" && (
            <p>Asigna Hero y al menos un rival para empezar.</p>
          )}
          {poker.status === "pending" && (
            <p role="status">Calculando el estado más reciente…</p>
          )}
          {poker.status === "error" && (
            <p role="alert">No se pudo calcular este estado.</p>
          )}
          {analysis && (
            <>
              <div className="poker-metrics">
                <div>
                  <span>Bote total</span>
                  <strong>{money(metrics?.pot_size, metrics?.unit)}</strong>
                </div>
                <div>
                  <span>Stack efectivo</span>
                  <strong>
                    {money(metrics?.effective_stack, metrics?.effective_unit)}
                  </strong>
                </div>
                <div>
                  <span>SPR actual</span>
                  <strong>{metrics?.spr?.toFixed(2) ?? "—"}</strong>
                </div>
                <div>
                  <span>Importe a igualar</span>
                  <strong>
                    {money(metrics?.to_call, metrics?.to_call_unit)}
                  </strong>
                </div>
                <div>
                  <span>Pot odds</span>
                  <strong>
                    {metrics?.pot_odds == null
                      ? "—"
                      : `${metrics.pot_odds.toFixed(2)} : 1`}
                  </strong>
                </div>
                <div>
                  <span>Equity mínima teórica</span>
                  <strong data-testid="required-equity">
                    {percent(metrics?.required_equity)}
                  </strong>
                </div>
                <div>
                  <span>Equity al showdown</span>
                  <strong data-testid="showdown-equity">
                    {percent(equity?.equity)}
                  </strong>
                </div>
              </div>
              {equity && (
                <p>
                  {equity.method === "exact_river_heads_up"
                    ? `Cálculo exacto sobre ${equity.samples} combos compatibles.`
                    : `${equity.samples} simulaciones · Intervalo del 95 %: ${percent(equity.interval_95[0])} – ${percent(equity.interval_95[1])}.`}{" "}
                  El intervalo solo mide el muestreo, no la fiabilidad del rango
                  ni del reconocimiento.
                </p>
              )}
              {(metrics?.effective_by_seat.length ?? 0) > 1 && (
                <p>
                  Stacks efectivos:{" "}
                  {metrics?.effective_by_seat
                    .map(
                      (p) =>
                        `asiento ${p.seat}: ${money(p.stack, metrics.effective_unit)}`,
                    )
                    .join(" · ")}
                </p>
              )}
              {analysis.postflop && (
                <PostflopAnalysis analysis={analysis.postflop} />
              )}
              {equity && (
                <p>
                  Rangos aplicados:{" "}
                  {equity.ranges
                    .map(
                      (p) =>
                        `asiento ${p.seat}: ${p.range} (${p.available_combos} combos)`,
                    )
                    .join(" · ")}
                </p>
              )}
              {analysis.range_provenance && (
                <p className="card-footnote">
                  Rangos adaptativos hasta el evento{" "}
                  {analysis.range_provenance.event_sequence} (
                  {analysis.range_provenance.timestamp.toFixed(1)} s).
                </p>
              )}
              {analysis.warnings.length > 0 && (
                <ul>
                  {analysis.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
              <p className="card-footnote">
                Datos de {analysis.timestamp?.toFixed(1) ?? "—"} s. Equity =
                parte media del bote al showdown, incluidos empates. No estima
                EV, apuestas futuras, rake ni botes laterales. Los importes sin
                unidad requieren que la mesa use una unidad común.
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}
