import { useEffect, useState } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";
import type { StrategyResult } from "../strategy/types";
import { StrategyColumn } from "../strategy/StrategyPanel";
import { BluffAnalysis } from "../strategy/BluffAnalysis";

type Comparison = {
  recommendation: {
    action: string;
    total_bb: number | null;
    ev_bb: number | null;
  };
  actual_ev_bb: number | null;
  ev_difference_bb: number | null;
  configured_frequency: number;
  size_in_original_menu: boolean;
};
type Evaluation = {
  status: string;
  result: {
    status: string;
    reason: string;
    actual_action: {
      action: string;
      total_bb?: number;
      timestamp: number;
    } | null;
    baseline: Comparison | null;
    exploitative: Comparison | null;
    confidence: { level: string; reason: string };
    strategy_result?: StrategyResult | null;
  } | null;
};
const action = (value: { action: string; total_bb?: number | null }) => {
  const label: Record<string, string> = {
    FOLD: "Fold",
    CHECK: "Check",
    CALL: "Call",
    BET: "Bet",
    RAISE: "Raise",
    ALL_IN: "All-in",
  };
  return (
    (label[value.action] ?? value.action) +
    (value.total_bb != null && ["BET", "RAISE", "ALL_IN"].includes(value.action)
      ? ` a ${value.total_bb.toFixed(1)} BB`
      : "")
  );
};
function difference(value: number | null) {
  if (value == null) return "No disponible";
  if (Math.abs(value) < 0.05) return "≈ 0,0 BB";
  return `≈ ${value > 0 ? "+" : ""}${value.toFixed(1)} BB`;
}

export function EvaluationReview({
  identity,
  accessGranted = false,
  detailed = false,
}: {
  identity: string;
  accessGranted?: boolean;
  detailed?: boolean;
}) {
  const { capture, available } = useCapture();
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const revision = capture.evaluations?.revision;
  const canRead =
    available &&
    (capture.decisions?.visibility === "training" ||
      (accessGranted && capture.feedback?.review_blocked === false));
  useEffect(() => {
    setEvaluation(null);
    setError(null);
    if (!canRead) return;
    const controller = new AbortController();
    fetch(`/api/decisions/${identity}/evaluation`, {
      signal: controller.signal,
    })
      .then(readResponse)
      .then((result) => {
        if (!controller.signal.aborted) setEvaluation(result as Evaluation);
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "No se pudo leer la evaluación.",
          );
      });
    return () => controller.abort();
  }, [identity, revision, canRead]);
  const result = canRead ? evaluation?.result : null;
  const strategy = result?.strategy_result;
  return (
    <section
      className="decision-evaluation"
      aria-label="Evaluación de la decisión"
      data-testid="decision-evaluation"
    >
      <h3>Después de actuar</h3>
      {(error || capture.evaluations?.storage_error) && (
        <p role="alert">{error || capture.evaluations?.storage_error}</p>
      )}
      {!result && !error && (
        <p role="status">
          {evaluation?.status === "waiting"
            ? "Todavía no hay una acción confirmada vinculada a esta decisión."
            : "Evaluación pendiente…"}
        </p>
      )}
      {result && (
        <>
          {result.actual_action && (
            <p>
              <strong>Acción de Hero: {action(result.actual_action)}</strong> ·{" "}
              {result.actual_action.timestamp.toFixed(1)} s
            </p>
          )}
          <p>{result.reason}</p>
          <div className="evaluation-comparisons">
            {(
              [
                ["Baseline", result.baseline],
                ["Explotativa", result.exploitative],
              ] as const
            ).map(
              ([title, comparison]) =>
                comparison && (
                  <article key={title}>
                    <h4>{title}</h4>
                    <p>Referencia: {action(comparison.recommendation)}</p>
                    <p>
                      Diferencia de EV:{" "}
                      <strong>{difference(comparison.ev_difference_bb)}</strong>
                    </p>
                    <p>
                      {comparison.ev_difference_bb == null
                        ? "La tabla no calcula EV."
                        : "Acción real menos la mejor opción configurada; no es el resultado de la mano."}
                    </p>
                    {!comparison.size_in_original_menu &&
                      comparison.ev_difference_bb != null && (
                        <p>
                          El tamaño real se evaluó por separado con los mismos
                          datos guardados.
                        </p>
                      )}
                    <small>
                      Frecuencia de esa acción y tamaño en la estrategia
                      original:{" "}
                      {Math.round(comparison.configured_frequency * 100)} %.
                    </small>
                  </article>
                ),
            )}
          </div>
          <p>
            Confianza{" "}
            {result.confidence.level === "limited"
              ? "limitada"
              : "insuficiente"}
            : {result.confidence.reason}
          </p>
          {detailed &&
            strategy?.status === "ready" &&
            strategy.baseline_strategy &&
            strategy.exploitative_strategy && (
              <details>
                <summary>Alternativas y análisis de farol</summary>
                <p>{strategy.reason}</p>
                {strategy.decision?.required_equity != null && (
                  <p>
                    Pot odds: equity mínima{" "}
                    {(strategy.decision.required_equity * 100).toFixed(0)} %.
                  </p>
                )}
                <div className="strategy-columns">
                  <StrategyColumn
                    title="Alternativas baseline"
                    strategy={strategy.baseline_strategy}
                    testId="review-baseline"
                  />
                  <StrategyColumn
                    title="Alternativas explotativas"
                    strategy={strategy.exploitative_strategy}
                    testId="review-exploit"
                  />
                </div>
                {strategy.bluff && <BluffAnalysis analysis={strategy.bluff} />}
              </details>
            )}
        </>
      )}
    </section>
  );
}
