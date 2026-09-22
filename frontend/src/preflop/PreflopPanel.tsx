import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";

const actions = {
  FOLD: "Fold",
  CHECK: "Check",
  CALL: "Call",
  RAISE: "Raise",
  ALL_IN: "All-in",
};

export function PreflopPanel() {
  const { capture, available, busy: captureBusy } = useCapture();
  const game = capture.observation_state.game_state;
  const preflop = capture.preflop;
  const serialized = JSON.stringify(preflop?.config || null);
  const [hero, setHero] = useState("");
  const [button, setButton] = useState("");
  const [seats, setSeats] = useState([1, 2, 3, 4, 5, 6]);
  const [ante, setAnte] = useState("0");
  const [includesBets, setIncludesBets] = useState("true");
  const [history, setHistory] = useState("[]");
  const [rules, setRules] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function loadDefaults(signal?: AbortSignal) {
    const defaults = await readResponse<{ rules: unknown[] }>(
      await fetch("/api/preflop/defaults", { signal }),
    );
    setRules(JSON.stringify(defaults.rules, null, 2));
  }
  useEffect(() => {
    const controller = new AbortController();
    loadDefaults(controller.signal).catch((error) => {
      if (!controller.signal.aborted) setError(error.message);
    });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const config = JSON.parse(serialized);
    setHero(config ? String(config.hero_seat) : "");
    setButton(config ? String(config.button_seat) : "");
    setSeats(config?.seats || [1, 2, 3, 4, 5, 6]);
    setAnte(config?.ante_total_bb || "0");
    setIncludesBets(String(config?.pot_includes_bets ?? true));
    setHistory(JSON.stringify(config?.prior_actions || [], null, 2));
    if (config) setRules(JSON.stringify(config.rules, null, 2));
    setConfirmed(false);
    setError(null);
  }, [serialized, game?.hand_id, capture.capture_id]);
  async function apply(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/preflop/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capture_id: capture.capture_id,
          state_revision: game?.revision,
          hand_id: game?.hand_id,
          hero_seat: Number(hero),
          button_seat: Number(button),
          seats,
          ante_total_bb: ante,
          pot_includes_bets: includesBets === "true",
          history_confirmed: confirmed,
          prior_actions: JSON.parse(history),
          rules: JSON.parse(rules),
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (response.status === 422) {
        const data = await response.json();
        throw new Error(
          Array.isArray(data.detail)
            ? data.detail.map((item: { msg: string }) => item.msg).join(" · ")
            : "Revisa la configuración preflop.",
        );
      }
      await readResponse(response);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudo aplicar el contexto preflop.",
      );
    } finally {
      setBusy(false);
    }
  }
  const ready =
    available &&
    !captureBusy &&
    capture.state === "running" &&
    game?.hand_status === "active" &&
    game.street === "preflop";
  const result = preflop?.result;
  return (
    <section
      className="panel poker-panel preflop-panel"
      aria-label="Estrategia preflop"
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">PRIMERA DECISIÓN</span>
          <h2>Estrategia preflop</h2>
        </div>
        <span className="outline-badge">Baseline configurable</span>
      </div>
      <p>
        Confirma el contexto de esta mano. La tabla de ejemplo cubre 20–200 BB
        sin antes: es una base de estudio, no una solución GTO.
      </p>
      <form onSubmit={apply}>
        <div className="poker-settings">
          <label>
            Hero preflop
            <select
              aria-label="Hero preflop"
              value={hero}
              onChange={(e) => setHero(e.target.value)}
            >
              <option value="">Sin confirmar</option>
              {seats.map((s) => (
                <option key={s} value={s}>
                  Asiento {s}
                </option>
              ))}
            </select>
          </label>
          <label>
            Botón de esta mano
            <select
              aria-label="Botón de esta mano"
              value={button}
              onChange={(e) => setButton(e.target.value)}
            >
              <option value="">Sin confirmar</option>
              {seats.map((s) => (
                <option key={s} value={s}>
                  Asiento {s}
                </option>
              ))}
            </select>
          </label>
          <label>
            Antes totales en BB
            <input
              aria-label="Antes totales en BB"
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={ante}
              onChange={(e) => setAnte(e.target.value)}
            />
          </label>
          <label>
            Bote preflop observado
            <select
              aria-label="Bote preflop observado"
              value={includesBets}
              onChange={(e) => setIncludesBets(e.target.value)}
            >
              <option value="true">Incluye apuestas de la calle</option>
              <option value="false">No incluye apuestas de la calle</option>
            </select>
          </label>
        </div>
        <fieldset>
          <legend>Asientos que recibieron cartas</legend>
          <p>
            Incluye también a quienes ya se retiraron. La numeración debe
            avanzar en sentido horario.
          </p>
          <div className="preflop-seats">
            {[1, 2, 3, 4, 5, 6].map((s) => (
              <label key={s}>
                <input
                  type="checkbox"
                  checked={seats.includes(s)}
                  onChange={(e) =>
                    setSeats(
                      e.target.checked
                        ? [...seats, s].sort()
                        : seats.filter((v) => v !== s),
                    )
                  }
                />{" "}
                Asiento {s}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="preflop-json">
          Acciones anteriores (JSON)
          <textarea
            aria-label="Acciones anteriores (JSON)"
            rows={3}
            maxLength={10000}
            value={history}
            onChange={(e) => {
              setHistory(e.target.value);
              setConfirmed(false);
            }}
          />
        </label>
        <small>
          [] confirma que todavía no hubo acciones voluntarias. Ejemplo: [
          {'{"seat":3,"action":"RAISE","total_bb":3}'},
          {'{"seat":4,"action":"FOLD"}'}]. total_bb es la apuesta total, no el
          incremento.
        </small>
        <details className="preflop-table">
          <summary>Editar rangos y condiciones de la tabla</summary>
          <p>
            La regla debe coincidir con posición, jugadores, stack, subida y
            antes. Si coinciden varias reglas, el motor no elige una
            arbitrariamente.
          </p>
          <textarea
            aria-label="Tabla preflop (JSON)"
            rows={12}
            maxLength={150000}
            value={rules}
            onChange={(e) => setRules(e.target.value)}
          />
          <button
            type="button"
            className="button secondary"
            onClick={() =>
              loadDefaults().catch((error) => setError(error.message))
            }
          >
            Cargar tabla de ejemplo
          </button>
        </details>
        <label className="preflop-confirm">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />{" "}
          He confirmado los asientos, el botón, los antes y todas las acciones
          anteriores de esta mano.
        </label>
        <button
          className="button secondary"
          disabled={!ready || busy || !hero || !button || !confirmed || !rules}
        >
          {busy ? "Guardando…" : "Aplicar contexto preflop"}
        </button>
        {!ready && (
          <small>
            Se necesita una captura en marcha con una mano preflop activa.
          </small>
        )}
        {error && <p role="alert">{error}</p>}
      </form>
      {preflop?.visibility !== "training" ? (
        <p className="card-notice">
          En dinero real los resultados se guardan internamente. Las acciones y
          tamaños sugeridos no se envían a esta vista.
        </p>
      ) : (
        <>
          {!available && (
            <p className="card-notice">
              Sin actualizaciones: no se muestra una recomendación conservada.
            </p>
          )}
          {available && result?.status === "ready" && (
            <div className="preflop-result" data-testid="preflop-result">
              <span>
                Tabla de estudio · Hero {preflop?.config?.hero_seat} ·{" "}
                {result.context.position}
              </span>
              <strong data-testid="preflop-action">
                {result.action && actions[result.action]}
              </strong>
              {result.sizing_bb != null && (
                <p data-testid="preflop-sizing">
                  Hasta {result.sizing_bb.toFixed(2)} BB en total · añadir{" "}
                  {result.additional_bb?.toFixed(2)} BB
                </p>
              )}
              <p>
                {result.context.effective_stack_bb?.toFixed(1)} BB efectivos ·{" "}
                {result.context.players_dealt} jugadores al reparto · regla{" "}
                {result.rule_id}
              </p>
              <small>
                Sin confianza estratégica calibrada. Resultado de los datos
                observados a {result.timestamp?.toFixed(1)} s; no incorpora
                acciones futuras.
              </small>
            </div>
          )}
          {available && result && <p>{result.reason}</p>}
          {preflop?.status === "unconfigured" && (
            <p>
              Confirma el contexto para esta mano. Se solicitará de nuevo en la
              siguiente.
            </p>
          )}
          {preflop?.status === "inactive" && (
            <p>Captura detenida. No hay una recomendación activa.</p>
          )}
          {preflop?.status === "storage_error" && (
            <p role="alert">
              No se pudo guardar el resultado; la captura debe detenerse y
              revisarse.
            </p>
          )}
        </>
      )}
    </section>
  );
}
