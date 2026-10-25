"""Verbalize recorded engine outputs. No solver, strategy choice or future state access."""
VERSION = "grounded-explainer-v1"
LABELS = {"FOLD": "Fold", "CHECK": "Check", "CALL": "Call", "BET": "Bet", "RAISE": "Raise", "ALL_IN": "All-in"}


def action(row):
    label = LABELS.get(row["action"], row["action"])
    size = row.get("total_bb")
    return label + (f" a {size:.1f} BB" if size is not None and row["action"] in {"BET", "RAISE", "ALL_IN"} else "")


def build_facts(record, strategy, evaluation, style):
    state = record["request"]["state"]
    advanced = style == "advanced"
    facts = []

    def add(identity, text, source, required=False):
        facts.append({"id": identity, "text": text, "source": source, "required": required})

    add("context", f"En {state['street']}, Hero tenía {' '.join(state['hero_cards'])}; "
        f"board: {' '.join(state['board']) or 'sin cartas comunitarias'}. "
        f"Bote observado: {state['pot']} {state.get('pot_unit') or '(unidad sin confirmar)' }.",
        "snapshot.request.state", True)
    if not record["history_complete"]:
        add("partial_history", "El historial era parcial: pueden faltar acciones anteriores. No se completan con información posterior.",
            "snapshot.history_complete", True)
    for key, label in (("baseline_strategy", "Baseline"), ("exploitative_strategy", "Explotativa")):
        table = strategy.get(key)
        if not table:
            continue
        options = table["options"]
        distribution = "; ".join(f"{action(row)}: {row['frequency'] * 100:.0f} %" for row in options)
        add(key, f"{label}: el motor repartía las frecuencias así: {distribution}. "
            "Una frecuencia indica mezcla de acciones, no probabilidad de acertar.", f"strategy.{key}.options", True)
        if table.get("equity") is not None:
            add(key + "_equity", f"{label}: equity estimada {table['equity'] * 100:.1f} %. "
                "Es la parte esperada del bote al comparar las cartas con el rango supuesto, antes de considerar todos los costes de jugar.",
                f"strategy.{key}.equity")
        if advanced:
            values = "; ".join(f"{action(row)}: {row['ev_bb']:.2f} BB" if row.get("ev_bb") is not None
                               else f"{action(row)}: EV no calculado" for row in options)
            add(key + "_ev", f"{label}, EV por alternativa: {values}. Valores del menú guardado; no se buscan otros tamaños.",
                f"strategy.{key}.options")
    decision = strategy.get("decision") or {}
    if decision.get("required_equity") is not None:
        add("pot_odds", f"Para igualar, el umbral aritmético de equity era {decision['required_equity'] * 100:.1f} %. "
            "Ese umbral por sí solo no decide una acción: el modelo también incluye realización de equity y riesgo.",
            "strategy.decision.required_equity")
    if advanced:
        amounts = [("pot_bb", "bote"), ("to_call_bb", "a igualar"), ("hero_stack_bb", "stack de Hero"), ("villain_stack_bb", "stack del rival"), ("effective_stack_bb", "stack efectivo")]
        known = [f"{label}: {decision[key]:.2f} BB" for key, label in amounts if decision.get(key) is not None]
        if known:
            add("amounts", "Importes del motor: " + "; ".join(known) + ".", "strategy.decision")
        prior_actions = [f"{event['type'].replace('PLAYER_', '')}"
                         + (f" {event['amount']} {event.get('unit') or ''}" if event.get("amount") else "")
                         for event in record["actions"][-6:]]
        if prior_actions:
            add("prior_actions", "Últimas acciones registradas antes de decidir: " + "; ".join(prior_actions) + ".",
                "snapshot.actions")
        tournament = strategy.get("tournament")
        if tournament and tournament.get("applied"):
            add("tournament", f"El motor aplicó un factor de riesgo de torneo de {tournament['risk_factor']:.2f}. Es un ajuste ilustrativo, no ICM.", "strategy.tournament")
        if decision.get("spr") is not None:
            add("spr", f"SPR guardado: {decision['spr']:.2f}. Expresa la relación entre stack efectivo y bote.", "strategy.decision.spr")
        frozen = record["request"].get("decision")
        if frozen:
            pools = frozen.get("exploit_pools", [])
            add("ranges", "Rangos adaptativos congelados: " + "; ".join(
                f"asiento {seat}, {len(pool)} combos ponderados" for seat, pool in pools) +
                ". Son supuestos de rango, no las cartas conocidas del rival.", "snapshot.request.decision.exploit_pools")
            counts = frozen.get("counts", [])
            rows = [f"asiento {seat}, {name}: {hits}/{n}" for seat, stats in counts for name, hits, n in stats]
            if rows:
                add("opponent_stats", "Muestras utilizadas por el motor: " + "; ".join(rows[:12]) +
                    ". Un recuento pequeño limita la fiabilidad del ajuste.", "snapshot.request.decision.counts")
        bluff = strategy.get("bluff") or {}
        case = bluff.get("exploit_strategy") or {}
        if case.get("applicable") and case.get("estimated_fold_frequency") is not None:
            text = f"Farol explotativo: fold estimado del rival {case['estimated_fold_frequency'] * 100:.1f} %."
            if case.get("required_fold_frequency") is not None:
                text += f" Fold requerido por el modelo para ese tamaño: {case['required_fold_frequency'] * 100:.1f} %."
            add("bluff", text + " Son estimaciones del motor para su rango supuesto.", "strategy.bluff.exploit_strategy")
    if evaluation and evaluation.get("actual_action"):
        add("actual_action", "La acción confirmada de Hero fue " + action(evaluation["actual_action"]) +
            ". Se utiliza para comparar con la estrategia congelada, sin cambiarla.", "evaluation.actual_action", True)
        for key, label in (("baseline", "baseline"), ("exploitative", "explotativa")):
            comparison = evaluation.get(key)
            if comparison and comparison.get("ev_difference_bb") is not None:
                add("comparison_" + key, f"Frente a la referencia {label}, la acción tuvo una diferencia estimada de "
                    f"{comparison['ev_difference_bb']:.2f} BB. Es EV de la acción menos el mejor EV del menú; no es dinero perdido ni el resultado de la mano.",
                    f"evaluation.{key}.ev_difference_bb", True)
    if state["street"] == "preflop":
        add("preflop_limit", "Preflop usa una tabla configurada. No hay cálculo de EV preflop ni un ajuste explotativo independiente.", "strategy.basis", True)
    add("limits", "El motor es heurístico y no está calibrado como un solver. La explicación organiza sus resultados; "
        "no recalcula estrategias ni incorpora cartas posteriores.", "strategy.basis", True)
    if advanced:
        for fact in facts:
            fact["required"] = True
    return facts
