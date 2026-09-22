import type { BluffAnalysis as Analysis, BluffCase, CardEffect } from "./types";
import { labels as hands } from "../poker/PostflopAnalysis";

const kinds: Record<string, string> = {
  value: "valor",
  bluff: "farol",
  semi_bluff: "semifarol",
};
const levels: Record<string, string> = {
  high: "alto",
  medium: "medio",
  low: "bajo",
};
const textures: Record<string, string> = {
  dry: "seco",
  semi_coordinated: "semicoordinado",
  coordinated: "coordinado",
};
const sides: Record<string, string> = {
  hero: "Hero",
  opponent: "rival",
  undetermined: "sin determinar",
  equal: "igual",
};
const sources: Record<string, string> = {
  fold_to_cbet: "Fold to CBet",
  wtsd_proxy: "proxy WTSD",
};
const statistics: [string, string][] = [
  ["fold_to_cbet", "Fold to CBet"],
  ["wtsd", "WTSD"],
  ["cbet", "CBet"],
  ["fold_to_three_bet", "Fold to 3Bet"],
  ["aggressive_share", "Agresividad postflop"],
];
const pct = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value * 100)} %`;

function sizing(item: BluffCase) {
  const size = item.recommended_sizing;
  if (!size) return "—";
  if (size.action === "BET" && size.sizing_pot != null)
    return `Bet ${Math.round(size.sizing_pot * 100)} % · ${size.total_bb.toFixed(1)} BB`;
  if (size.action === "ALL_IN")
    return `All-in · ${size.total_bb.toFixed(1)} BB`;
  return `Raise a ${size.total_bb.toFixed(1)} BB`;
}

function effects(items: CardEffect[] | undefined, empty: string) {
  if (!items?.length) return empty;
  return items
    .map(
      (e) =>
        `${e.card} (retira ${pct(e.continuing_removed)} de lo que continúa y ${pct(e.folding_removed)} de lo que se retira)`,
    )
    .join(" · ");
}

function source(item: BluffCase) {
  const statistic = item.fold_source?.statistic;
  if (!statistic) return "Defensa equilibrada";
  return `${sources[statistic] ?? statistic} · n = ${item.fold_source?.opportunities ?? 0}`;
}

export function BluffAnalysis({ analysis }: { analysis: Analysis }) {
  if (!analysis.applicable)
    return (
      <section
        className="bluff-analysis"
        data-testid="bluff-analysis"
        aria-label="Análisis de farol"
      >
        <h3>Análisis de farol</h3>
        <p>{analysis.reason}</p>
      </section>
    );
  const exploit = analysis.exploit_strategy!;
  const baseline = analysis.baseline_strategy!;
  const tendencies = analysis.player_tendencies?.statistics ?? {};
  const ranges = analysis.range_advantage?.exploit;
  const rows: [string, (item: BluffCase) => string][] = [
    ["Clasificación", (i) => kinds[i.classification ?? ""] ?? "—"],
    ["Candidato", (i) => (i.bluff_candidate ? "Sí" : "No")],
    ["Tamaño", sizing],
    ["Fold estimado", (i) => pct(i.estimated_fold_frequency)],
    ["Fold necesario", (i) => pct(i.required_fold_frequency)],
    [
      "Mejora frente a pasar",
      (i) =>
        i.ev_gain_bb == null
          ? "—"
          : `${i.ev_gain_bb >= 0 ? "+" : ""}${i.ev_gain_bb.toFixed(1)} BB`,
    ],
    ["Frecuencia de farol", (i) => pct(i.bluff_frequency)],
    ["Origen del fold", source],
  ];
  return (
    <section
      className="bluff-analysis"
      data-testid="bluff-analysis"
      aria-label="Análisis de farol"
    >
      <h3>Análisis de farol</h3>
      <p data-testid="bluff-verdict">
        <strong>
          {analysis.bluff_candidate
            ? `Candidato a ${kinds[exploit.classification ?? ""]}`
            : exploit.classification === "value"
              ? "Apuesta de valor, no farol"
              : "Sin farol recomendado"}
        </strong>{" "}
        · {analysis.reason}
      </p>
      <div
        className="bluff-grid"
        role="table"
        aria-label="Farol baseline y explotativo"
      >
        <div role="row">
          <span role="columnheader" />
          <span role="columnheader">Baseline</span>
          <span role="columnheader">Explotativa</span>
        </div>
        {rows.map(([label, value]) => (
          <div role="row" key={label}>
            <span role="rowheader">{label}</span>
            <span role="cell">{value(baseline)}</span>
            <span role="cell">{value(exploit)}</span>
          </div>
        ))}
      </div>
      <ul>
        <li>
          Valor de showdown {levels[analysis.showdown_value?.category ?? ""]}:{" "}
          {pct(analysis.showdown_value?.equity)} de equity contra el rango
          completo (
          {hands[analysis.showdown_value?.hand ?? ""] ??
            analysis.showdown_value?.hand}
          ).
        </li>
        <li>
          Bloqueadores: {effects(analysis.blockers, "ninguno")}. Efecto sobre el
          fold:{" "}
          {exploit.fold_shift_from_blockers != null
            ? `${exploit.fold_shift_from_blockers >= 0 ? "+" : ""}${(exploit.fold_shift_from_blockers * 100).toFixed(1)} pp`
            : "—"}
          .
        </li>
        <li>
          Dejan intactos los folds del rival:{" "}
          {analysis.unblockers?.length
            ? analysis.unblockers.map((e) => e.card).join(", ")
            : "ninguna carta"}
          .
        </li>
        <li>
          Proyectos: {analysis.draws?.completion_count ?? 0} cartas de
          finalización
          {analysis.draws?.backdoor ? " · backdoor" : ""}. Board{" "}
          {textures[analysis.board_texture?.texture ?? ""] ?? "—"} · SPR{" "}
          {analysis.spr?.toFixed(2) ?? "—"}.
        </li>
        {ranges && (
          <li>
            Rangos percibidos: Hero {pct(ranges.hero_equity)} de equity ·
            ventaja de rango {sides[ranges.range_advantage]} · densidad de nuts{" "}
            {sides[ranges.nut_advantage_proxy]}.
          </li>
        )}
        <li>
          Tendencias del rival:{" "}
          {statistics
            .filter(([key]) => tendencies[key])
            .map(
              ([key, label]) =>
                `${label} ${tendencies[key].hits}/${tendencies[key].opportunities} (${pct(tendencies[key].rate)} suavizado)`,
            )
            .join(" · ")}
          .
        </li>
      </ul>
    </section>
  );
}
