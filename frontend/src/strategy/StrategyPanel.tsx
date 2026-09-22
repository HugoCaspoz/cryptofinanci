import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";
import type { Strategy, StrategyAction, StrategyOption } from "./types";
import { BluffAnalysis } from "./BluffAnalysis";

const labels: Record<StrategyAction, string> = {
  FOLD: "Fold",
  CHECK: "Check",
  CALL: "Call",
  BET: "Bet",
  RAISE: "Raise",
  ALL_IN: "All-in",
};
const stages: Record<string, string> = {
  unknown: "fase sin determinar",
  early: "lejos de premios",
  approaching_money: "cerca de premios",
  bubble: "burbuja",
  in_the_money: "en premios",
};
const whole = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value * 100)} %`;
const bb = (value: number | null | undefined) =>
  value == null ? "—" : `${value.toFixed(1)} BB`;

function optionLabel(option: StrategyOption) {
  if (option.action === "BET" && option.sizing_pot != null)
    return `Bet ${Math.round(option.sizing_pot * 100)} % del bote · ${bb(option.total_bb)}`;
  if (option.action === "RAISE") return `Raise a ${bb(option.total_bb)}`;
  if (option.action === "ALL_IN") return `All-in · ${bb(option.total_bb)}`;
  if (option.action === "CALL")
    return `Call ${bb(option.added_bb)}${option.all_in ? " (all-in)" : ""}`;
  return labels[option.action];
}

export function StrategyColumn({
  title,
  strategy,
  testId,
}: {
  title: string;
  strategy: Strategy;
  testId: string;
}) {
  return (
    <article
      className="strategy-column"
      data-testid={testId}
      aria-label={title}
    >
      <h3>{title}</h3>
      <p className="strategy-summary">
        {Object.entries(strategy.summary)
          .map(
            ([action, value]) =>
              `${labels[action as StrategyAction]} ${whole(value)}`,
          )
          .join(" · ")}
      </p>
      <ul>
        {strategy.options.map((option, index) => (
          <li key={index}>
            <div>
              <span>{optionLabel(option)}</span>
              <strong>{whole(option.frequency)}</strong>
            </div>
            <span
              className="strategy-bar"
              style={{ width: `${Math.round(option.frequency * 100)}%` }}
            />
            <small>
              {option.ev_bb == null
                ? "Tabla configurada, sin EV"
                : option.action === "FOLD"
                  ? "Referencia: EV 0"
                  : `EV ≈ ${option.ev_bb >= 0 ? "+" : ""}${option.ev_bb.toFixed(1)} BB`}
              {option.fold_probability != null &&
                ` · fold rival ${whole(option.fold_probability)} · equity si paga ${whole(option.equity_when_called)}`}
            </small>
          </li>
        ))}
      </ul>
      {strategy.equity != null && (
        <small>Equity contra el rango: {whole(strategy.equity)}</small>
      )}
    </article>
  );
}

export function StrategyPanel() {
  const { capture, available } = useCapture();
  const strategy = capture.strategy;
  const saved = JSON.stringify(strategy?.config ?? null);
  const [sizes, setSizes] = useState("33, 75");
  const [multiplier, setMultiplier] = useState("3");
  const [temperature, setTemperature] = useState("5");
  const [tournament, setTournament] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const config = JSON.parse(saved);
    if (!config) return;
    setSizes(
      config.bet_sizes.map((size: number) => Math.round(size * 100)).join(", "),
    );
    setMultiplier(String(config.raise_multiplier));
    setTemperature(String(Math.round(config.temperature * 100)));
    setTournament(config.tournament_adjustment);
  }, [saved]);
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/strategy/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bet_sizes: sizes
            .split(",")
            .filter((value) => value.trim())
            .map((value) => Number(value) / 100),
          raise_multiplier: Number(multiplier),
          temperature: Number(temperature) / 100,
          tournament_adjustment: tournament,
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (response.status === 422) {
        const data = await response.json();
        throw new Error(
          Array.isArray(data.detail)
            ? data.detail.map((item: { msg: string }) => item.msg).join(" · ")
            : "Revisa los tamaños de la estrategia.",
        );
      }
      await readResponse(response);
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
  const result = available ? strategy?.result : null;
  const decision = result?.decision;
  return (
    <section
      className="panel poker-panel strategy-panel"
      aria-label="Motor de estrategia"
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">BASELINE Y AJUSTES</span>
          <h2>Motor de estrategia</h2>
        </div>
        <span className="outline-badge">
          {strategy?.visibility === "training"
            ? "Entrenamiento"
            : "Archivo interno"}
        </span>
      </div>
      <p>
        Combina estado, motor matemático, modelo de rivales y torneo en cada
        decisión de Hero. Usa el Hero y la convención de bote del motor
        matemático; postflop requiere el inicio confirmado en el modelo de
        rivales y preflop, el contexto de la tabla preflop.
      </p>
      <p>
        Cada turno conserva los datos y ajustes de su primera instantánea. Los
        cambios de configuración se aplican a las siguientes decisiones.
      </p>
      <form onSubmit={save}>
        <details>
          <summary>Tamaños y dispersión</summary>
          <div className="poker-settings">
            <label>
              Tamaños de apuesta (% del bote)
              <input
                aria-label="Tamaños de apuesta (% del bote)"
                value={sizes}
                maxLength={40}
                onChange={(e) => setSizes(e.target.value)}
              />
            </label>
            <label>
              Subida (× apuesta rival)
              <input
                aria-label="Subida (× apuesta rival)"
                type="number"
                min="2"
                max="6"
                step="0.1"
                value={multiplier}
                onChange={(e) => setMultiplier(e.target.value)}
              />
            </label>
            <label>
              Dispersión (% del bote)
              <input
                aria-label="Dispersión (% del bote)"
                type="number"
                min="1"
                max="50"
                step="1"
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
              />
            </label>
            <label className="strategy-check">
              <input
                type="checkbox"
                checked={tournament}
                onChange={(e) => setTournament(e.target.checked)}
              />{" "}
              Aplicar riesgo de torneo
            </label>
          </div>
          <small>
            La dispersión reparte frecuencias entre acciones de EV parecido: una
            diferencia igual a ese porcentaje del bote multiplica por e ≈ 2,7 la
            preferencia. El riesgo de torneo es un factor ilustrativo, no ICM.
          </small>
          <button className="button secondary" disabled={busy || !available}>
            {busy ? "Aplicando…" : "Aplicar tamaños"}
          </button>
        </details>
        {error && <p role="alert">{error}</p>}
      </form>
      {strategy?.storage_error && <p role="alert">{strategy.storage_error}</p>}
      {strategy?.visibility !== "training" ? (
        <p className="card-notice">
          En dinero real la estrategia se calcula y archiva en privado en cada
          decisión de Hero. No se envía a esta vista durante la mano.
        </p>
      ) : (
        <>
          {!available && (
            <p className="card-notice">
              Sin actualizaciones: no se muestra una estrategia conservada.
            </p>
          )}
          {available && strategy.status === "inactive" && (
            <p>Sin captura en marcha.</p>
          )}
          {available && strategy.status === "pending" && (
            <p role="status">Calculando la decisión más reciente…</p>
          )}
          {available && strategy.status === "error" && (
            <p role="alert">No se pudo calcular la estrategia.</p>
          )}
          {result && result.status !== "ready" && (
            <p data-testid="strategy-reason">{result.reason}</p>
          )}
          {result?.status === "ready" &&
            result.baseline_strategy &&
            result.exploitative_strategy && (
              <div data-testid="strategy-result">
                <p className="strategy-decision">
                  Decisión de Hero · {result.street}
                  {decision?.position &&
                    ` · ${decision.position === "in_position" ? "en posición" : decision.position === "out_of_position" ? "fuera de posición" : decision.position}`}
                  {decision?.pot_bb != null &&
                    ` · bote ${bb(decision.pot_bb)} · a igualar ${bb(decision.to_call_bb)}`}
                  {decision?.required_equity != null &&
                    ` · equity mínima ${whole(decision.required_equity)}`}
                </p>
                {result.tournament && (
                  <p className="strategy-decision">
                    Torneo:{" "}
                    {stages[result.tournament.stage] ?? result.tournament.stage}
                    {result.tournament.applied
                      ? ` · coste de fichas perdidas ×${result.tournament.risk_factor}`
                      : " · sin ajuste de riesgo"}
                  </p>
                )}
                <div className="strategy-columns">
                  <StrategyColumn
                    title="Baseline"
                    strategy={result.baseline_strategy}
                    testId="strategy-baseline"
                  />
                  <StrategyColumn
                    title="Explotativa"
                    strategy={result.exploitative_strategy}
                    testId="strategy-exploit"
                  />
                </div>
                {result.bluff && <BluffAnalysis analysis={result.bluff} />}
                <ul className="strategy-adjustments">
                  {result.adjustments.map((item) => (
                    <li key={item.input}>
                      {item.input === "villain_range" &&
                      item.baseline &&
                      item.exploit
                        ? `Rango del rival: ${item.baseline.effective_combos.toFixed(0)} → ${item.exploit.effective_combos.toFixed(0)} combos efectivos; equity ${whole(item.baseline.equity)} → ${whole(item.exploit.equity)}.`
                        : item.input === "fold_probability" && item.applied
                          ? `Fold to CBet ${item.hits}/${item.opportunities}; peso de los datos ${whole(item.data_weight)}. ${item.reason}`
                          : item.reason}
                    </li>
                  ))}
                </ul>
                <small className="strategy-footnote">
                  {result.reason} Datos de {result.timestamp?.toFixed(1) ?? "—"}{" "}
                  s; sin acciones futuras. Frecuencias redondeadas; no son una
                  confianza calibrada.
                </small>
              </div>
            )}
        </>
      )}
    </section>
  );
}
