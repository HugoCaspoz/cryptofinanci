import { useRef, useState } from "react";
import { useCapture } from "./CaptureProvider";
import type { GameState } from "../game/types";
import "../styles/corrections.css";

const actions = [
  "NONE",
  "ACTIVE",
  "FOLD",
  "CHECK",
  "CALL",
  "BET",
  "RAISE",
  "ALL-IN",
];
const units = ["", "$", "€", "£", "BB"];

async function mutate(url: string, body?: unknown) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) {
    const result = await response.json();
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : result.detail?.[0]?.msg || "No se pudo aplicar el cambio.",
    );
  }
}

export function ManualCorrection() {
  const { capture, available } = useCapture();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const paused = capture.analysis_control?.paused ?? false;
  const control = capture.analysis_control;
  const game = capture.observation_state.game_state;
  async function toggle() {
    setBusy(true);
    setError("");
    try {
      await mutate(
        `/api/capture/${capture.capture_id}/analysis/${paused ? "resume" : "pause"}`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "No se pudo cambiar la pausa.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="panel manual-correction">
      <summary>
        Corrección manual ·{" "}
        {capture.state !== "running"
          ? "Sin análisis activo"
          : paused
            ? "Análisis pausado"
            : "Observando"}
      </summary>
      <div className="correction-body">
        <p>
          Pausa para corregir la lectura del frame actual. Se conserva la misma
          captura y se guarda cada ajuste con su imagen en el dataset.
        </p>
        <button
          className="button secondary"
          disabled={!available || busy || capture.state !== "running"}
          onClick={() => void toggle()}
        >
          {paused ? "Reanudar análisis" : "Pausar análisis"}
        </button>
        {paused && game && game.frame_id !== null && control && (
          <CorrectionForm
            key={`${capture.server_id}:${capture.capture_id}:${control.revision}`}
            game={game}
            captureId={capture.capture_id!}
            revision={control.revision}
            disabled={!available || busy || capture.state !== "running"}
          />
        )}
        {paused && (!game || game.frame_id === null) && (
          <p>Todavía no hay un frame analizado. Reanuda para recibirlo.</p>
        )}
        {control?.last_correction_id && (
          <p role="status">Corrección guardada en el dataset.</p>
        )}
        {error && <p role="alert">{error}</p>}
        {capture.capture_id && (
          <a
            href={`/api/capture/${capture.capture_id}/corrections`}
            target="_blank"
            rel="noreferrer"
          >
            Abrir dataset de esta captura (JSON)
          </a>
        )}
        <p>
          Las lecturas nuevas pueden sustituir los valores corregidos al
          reanudar. El historial estratégico afectado necesita reconfirmación;
          las decisiones archivadas conservan sus datos originales.
        </p>
      </div>
    </details>
  );
}

function CorrectionForm({
  game,
  captureId,
  revision,
  disabled,
}: {
  game: GameState;
  captureId: string;
  revision: number;
  disabled: boolean;
}) {
  const [hero, setHero] = useState(game.hero_cards.join(" "));
  const [board, setBoard] = useState(game.board.join(" "));
  const [players, setPlayers] = useState(
    game.players.map((p) => ({
      seat: p.seat,
      nickname: p.nickname ?? "",
      stack: p.stack ?? "",
      stackUnit: p.stack_unit ?? "",
      bet: p.current_bet ?? "",
      betUnit: p.bet_unit ?? "",
      action: p.observed_action ?? "NONE",
    })),
  );
  const requestRef = useRef<{ id: string; content: string } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const cards = (value: string) =>
    value.trim()
      ? value
          .trim()
          .split(/\s+/)
          .map((c) => c[0].toUpperCase() + c.slice(1).toLowerCase())
      : [];
  function patch() {
    const result: Record<string, unknown> = {};
    if (hero !== game.hero_cards.join(" ")) result.hero_cards = cards(hero);
    if (board !== game.board.join(" ")) result.board = cards(board);
    const edits = players
      .map((p, i) => {
        const old = game.players[i];
        const edit: Record<string, unknown> = { seat: p.seat };
        if (p.nickname !== (old.nickname ?? ""))
          edit.nickname = p.nickname || null;
        if (
          p.stack !== (old.stack ?? "") ||
          p.stackUnit !== (old.stack_unit ?? "")
        )
          edit.stack = p.stack
            ? { value: p.stack, unit: p.stackUnit || null }
            : null;
        if (
          p.bet !== (old.current_bet ?? "") ||
          p.betUnit !== (old.bet_unit ?? "")
        )
          edit.bet = p.bet ? { value: p.bet, unit: p.betUnit || null } : null;
        if (p.action !== (old.observed_action ?? "NONE"))
          edit.action = p.action;
        return edit;
      })
      .filter((p) => Object.keys(p).length > 1);
    if (edits.length) result.players = edits;
    return result;
  }
  async function save() {
    setBusy(true);
    setMessage("");
    try {
      const content = JSON.stringify({ reason, ...patch() });
      if (requestRef.current?.content !== content)
        requestRef.current = { id: crypto.randomUUID(), content };
      await mutate(`/api/capture/${captureId}/corrections`, {
        id: requestRef.current.id,
        expected_frame_id: game.frame_id,
        expected_revision: revision,
        reason,
        ...patch(),
      });
      setMessage("Corrección guardada en el dataset.");
    } catch (cause) {
      setMessage(
        cause instanceof Error
          ? cause.message
          : "No se pudo guardar la corrección.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <p>
        Frame {game.frame_id} · {game.timestamp?.toFixed(3)} s. Las apuestas son
        el total visible en la calle.
      </p>
      <fieldset disabled={disabled || busy}>
        <label>
          Cartas de Hero
          <input
            value={hero}
            onChange={(e) => setHero(e.target.value)}
            placeholder="As Kd"
          />
        </label>
        <label>
          Board corregido
          <input
            value={board}
            onChange={(e) => setBoard(e.target.value)}
            placeholder="2h 7c Td"
          />
        </label>
        <p>
          Usa rangos 2–9, T, J, Q, K, A y palos s, h, d, c, separados por
          espacios. Vaciar un campo elimina su lectura.
        </p>
        {players.map((p, i) => (
          <fieldset className="correction-player" key={p.seat}>
            <legend>Asiento {p.seat}</legend>
            {(
              [
                ["nickname", "Jugador"],
                ["stack", "Stack"],
                ["bet", "Apuesta"],
              ] as const
            ).map(([key, title]) => (
              <label key={key}>
                {title} asiento {p.seat}
                <input
                  value={p[key]}
                  maxLength={key === "nickname" ? 32 : 15}
                  onChange={(e) =>
                    setPlayers(
                      players.map((old, j) =>
                        j === i ? { ...old, [key]: e.target.value } : old,
                      ),
                    )
                  }
                />
              </label>
            ))}
            {(
              [
                ["stackUnit", "Unidad de stack"],
                ["betUnit", "Unidad de apuesta"],
              ] as const
            ).map(([key, title]) => (
              <label key={key}>
                {title} asiento {p.seat}
                <select
                  value={p[key]}
                  onChange={(e) =>
                    setPlayers(
                      players.map((old, j) =>
                        j === i ? { ...old, [key]: e.target.value } : old,
                      ),
                    )
                  }
                >
                  {units.map((unit) => (
                    <option key={unit} value={unit}>
                      {unit || "Fichas"}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <label>
              Acción asiento {p.seat}
              <select
                value={p.action}
                onChange={(e) =>
                  setPlayers(
                    players.map((old, j) =>
                      j === i ? { ...old, action: e.target.value } : old,
                    ),
                  )
                }
              >
                {actions.map((action) => (
                  <option key={action} value={action}>
                    {action === "NONE"
                      ? "Sin acción"
                      : action === "ACTIVE"
                        ? "Turno activo"
                        : action}
                  </option>
                ))}
              </select>
            </label>
          </fieldset>
        ))}
        <label>
          Motivo de la corrección
          <input
            required
            maxLength={240}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <button
          className="button primary"
          disabled={!Object.keys(patch()).length || !reason.trim()}
        >
          Guardar corrección
        </button>
      </fieldset>
      {message && <p role="status">{message}</p>}
    </form>
  );
}
