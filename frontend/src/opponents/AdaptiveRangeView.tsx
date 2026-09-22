import type { AdaptiveRange } from "./types";

const status: Record<string, string> = {
  active: "En seguimiento",
  folded: "Retirado",
  empty: "Sin combos compatibles",
  invalid: "Suspendido: historial incompleto",
  finished: "Mano terminada",
};
const pct = (n: number) => `${(100 * n).toFixed(1)} %`;

export function AdaptiveRangeView({ range }: { range: AdaptiveRange }) {
  const last = range.last_update;
  return (
    <div
      className="adaptive-range"
      data-testid={`adaptive-range-${range.seat}`}
    >
      <h4>Rango adaptativo · {status[range.status]}</h4>
      {range.status !== "invalid" && (
        <>
          <p>
            {range.available_combos} combos compatibles ·{" "}
            {range.effective_combos.toFixed(1)} efectivos
          </p>
          <p className="card-footnote">
            Los efectivos miden concentración de pesos, no certeza.
          </p>
          <p>
            {range.top_classes
              .map((c) => `${c.hand} ${pct(c.weight)}`)
              .join(" · ")}
          </p>
          {last ? (
            <div className="card-footnote">
              Evento {last.event_sequence}: {last.action}.{" "}
              {last.update === "neutral"
                ? "Sin reponderación."
                : `${last.evidence.statistic}: tasa suavizada ${pct(last.evidence.rate)}; peso de datos ${pct(last.evidence.data_weight)} (${last.evidence.opportunities} oportunidades anteriores).`}
              {last.update !== "neutral" &&
                last.evidence.prior_source?.kind === "tournament" && (
                  <p>
                    Prior de torneo: {last.evidence.prior_source.label} (
                    {last.evidence.prior_source.buy_in}{" "}
                    {last.evidence.prior_source.currency}) · Peso del prior{" "}
                    {pct(last.evidence.prior_weight)}.
                  </p>
                )}
            </div>
          ) : (
            <p className="card-footnote">
              Rango inicial; aún no hay acciones confirmadas.
            </p>
          )}
        </>
      )}
    </div>
  );
}
