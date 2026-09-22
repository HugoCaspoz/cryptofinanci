import { useEffect, useState } from "react";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";
import type { DecisionSummary, DecisionDetail } from "../decisions/types";
import { EvaluationReview } from "../decisions/EvaluationReview";

type Access = {
  allowed: boolean;
  reason: string;
  can_finish: boolean;
  session: { scope_id: string; status: string; release_policy: string } | null;
};

function FrozenReview({ identity }: { identity: string }) {
  const [data, setData] = useState<DecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/decisions/${identity}`, { signal: controller.signal })
      .then(readResponse<DecisionDetail>)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [identity]);
  return (
    <>
      {error ? (
        <p role="alert">{error}</p>
      ) : data ? (
        <article data-testid="historical-decision">
          <h3>Datos al decidir · {data.timestamp.toFixed(1)} s</h3>
          <p>
            Hero: {data.request.state.hero_cards.join(" ")} · Board:{" "}
            {data.request.state.board.join(" ") || "Preflop"} · Bote:{" "}
            {data.request.state.pot}
          </p>
          {!data.history_complete && (
            <p>Historial parcial: pueden faltar acciones anteriores.</p>
          )}
          <EvaluationReview identity={identity} accessGranted detailed />
        </article>
      ) : (
        <p>Cargando decisión…</p>
      )}
    </>
  );
}

function Decisions({ handId }: { handId: string }) {
  const [after, setAfter] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [data, setData] = useState<{
    items: DecisionSummary[];
    has_more: boolean;
    next_after: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    setSelected(null);
    fetch(
      `/api/decisions?hand_id=${encodeURIComponent(handId)}&after=${after}`,
      { signal: controller.signal },
    )
      .then(readResponse<typeof data>)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [handId, after]);
  return (
    <>
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          {data.items.length === 0 && (
            <p>No hay instantáneas de decisión guardadas para esta mano.</p>
          )}
          <ul className="decision-list">
            {data.items.map((item) => (
              <li key={item.id}>
                <button
                  className="button secondary"
                  aria-pressed={selected === item.id}
                  onClick={() => setSelected(item.id)}
                >
                  Revisar {item.street} · {item.timestamp.toFixed(1)} s
                </button>
              </li>
            ))}
          </ul>
          {after > 0 && (
            <button className="button secondary" onClick={() => setAfter(0)}>
              Primeras decisiones
            </button>
          )}
          {data.has_more && (
            <button
              className="button secondary"
              onClick={() => setAfter(data.next_after)}
            >
              Siguientes decisiones
            </button>
          )}
          {selected && <FrozenReview key={selected} identity={selected} />}
        </>
      )}
    </>
  );
}

export function HandReview({ handId }: { handId: string }) {
  const { capture, available } = useCapture();
  const blocked = !available || capture.feedback?.review_blocked !== false;
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<{ key: string; value: Access } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify([
    handId,
    capture.server_id,
    capture.capture_id,
    capture.feedback?.revision,
    blocked,
    attempt,
  ]);
  useEffect(() => {
    setData(null);
    setError(null);
    setFinished(false);
    if (!available) return;
    const controller = new AbortController();
    fetch(`/api/feedback/hands/${encodeURIComponent(handId)}`, {
      signal: controller.signal,
    })
      .then(readResponse<Access>)
      .then((value) => {
        if (!controller.signal.aborted) setData({ key, value });
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [key, available, handId]);
  const info = data?.key === key ? data.value : null;
  async function finish() {
    if (!info?.session) return;
    setBusy(true);
    setError(null);
    try {
      await readResponse(
        await fetch(`/api/feedback/sessions/${info.session.scope_id}/finish`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_finished: finished }),
        }),
      );
      setAttempt((a) => a + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cerrar la sesión.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="panel hand-panel review-panel"
      aria-label="Revisión de la mano"
    >
      <h2>Revisión de la mano</h2>
      <p>
        {blocked
          ? !available
            ? "Sin conexión: revisión oculta."
            : "Revisión oculta durante la mano activa o el inicio de la captura."
          : (info?.reason ?? "Consultando acceso…")}
      </p>
      {error && <p role="alert">{error}</p>}
      {info?.session && (
        <p>
          Política de esta captura:{" "}
          {info.session.release_policy === "HAND_FINISHED"
            ? "tras cada mano confirmada"
            : "al finalizar la sesión"}
          .
        </p>
      )}
      {info?.can_finish && !blocked && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void finish();
          }}
        >
          <label>
            <input
              type="checkbox"
              checked={finished}
              onChange={(e) => setFinished(e.target.checked)}
            />{" "}
            He terminado la sesión de juego de esta captura
          </label>
          <button className="button secondary" disabled={!finished || busy}>
            Finalizar sesión y abrir revisión
          </button>
        </form>
      )}
      <button
        className="button secondary"
        disabled={!available || busy}
        onClick={() => setAttempt((a) => a + 1)}
      >
        Actualizar revisión
      </button>
      {!blocked && info?.allowed && <Decisions key={key} handId={handId} />}
    </section>
  );
}
