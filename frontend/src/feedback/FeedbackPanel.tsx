import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useCapture } from "../capture/CaptureProvider";
import { readResponse } from "../capture/types";

export function FeedbackPanel() {
  const { capture, available } = useCapture();
  const feedback = capture.feedback;
  const [release, setRelease] = useState("SESSION_FINISHED");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (feedback) setRelease(feedback.next_release);
  }, [feedback?.next_release]);
  async function save() {
    setBusy(true);
    setError(null);
    try {
      await readResponse(
        await fetch("/api/feedback/config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ release }),
        }),
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No se pudo guardar la política.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel poker-panel" aria-label="Acceso a la revisión">
      <div className="section-heading">
        <h2>Acceso a la revisión</h2>
      </div>
      <p>
        En entrenamiento el análisis está disponible durante la práctica. En
        dinero real se abre según la política de cada captura y se oculta al
        detectar otra mano activa.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <label>
          Revisión en dinero real para la siguiente captura
          <select
            aria-label="Momento de revisión"
            value={release}
            onChange={(e) => setRelease(e.target.value)}
            disabled={!available || capture.state === "running" || busy}
          >
            <option value="SESSION_FINISHED">Al finalizar la sesión</option>
            <option value="HAND_FINISHED">Tras cada mano confirmada</option>
          </select>
        </label>
        <button
          className="button secondary"
          disabled={!available || capture.state === "running" || busy}
        >
          Guardar política de revisión
        </button>
      </form>
      <p>
        La política queda fijada al iniciar la captura. Detener la fuente no
        declara finalizada la sesión de juego. Puedes cerrarla y consultar los
        análisis desde el detalle de una mano guardada.
      </p>
      {feedback?.session_release && (
        <p>
          Captura actual:{" "}
          {feedback.session_release === "HAND_FINISHED"
            ? "revisión tras cada mano confirmada"
            : "revisión al finalizar la sesión"}
          .
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <p>
        <Link className="text-link" to="/hands">
          Abrir manos guardadas
        </Link>
      </p>
    </section>
  );
}
