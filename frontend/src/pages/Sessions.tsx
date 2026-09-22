import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { Icon } from "../components/Icon";

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="panel empty-state">
      <div className="empty-icon">
        <Icon name="sessions" size={30} />
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      <Link to="/live" className="button primary">
        Ir al panel en directo <Icon name="arrow" size={17} />
      </Link>
    </div>
  );
}

export function Sessions() {
  const [state, setState] = useState<"loading" | "empty" | "error">("loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    fetch("/api/sessions", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load sessions");
        const data = await response.json();
        if (!Array.isArray(data.items) || data.total !== 0)
          throw new Error("Unexpected session response");
        setState("empty");
      })
      .catch((error) => {
        if (error.name !== "AbortError") setState("error");
      });
    return () => controller.abort();
  }, [attempt]);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">CADA MANO CUENTA</span>
          <h1>Tus sesiones</h1>
          <p>Un lugar para volver a tus decisiones y seguir aprendiendo.</p>
        </div>
      </div>
      {state === "loading" && (
        <p role="status" className="muted">
          Consultando sesiones…
        </p>
      )}
      {state === "empty" && (
        <EmptyState
          title="Tu historia todavía está por escribir."
          description="La agrupación de sesiones llegará en una próxima fase. Las manos observadas están disponibles en la sección Manos."
        />
      )}
      {state === "error" && (
        <div className="panel error-state" role="alert">
          <h2>No se pudieron cargar las sesiones.</h2>
          <p>Comprueba que el backend esté en marcha y vuelve a intentarlo.</p>
          <button
            className="button secondary"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Reintentar
          </button>
        </div>
      )}
    </>
  );
}

export function SessionDetail() {
  const { id } = useParams();
  const [state, setState] = useState<"loading" | "missing" | "error">(
    "loading",
  );
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    fetch(`/api/sessions/${encodeURIComponent(id ?? "")}`, {
      signal: controller.signal,
    })
      .then((response) => {
        setState(response.status === 404 ? "missing" : "error");
      })
      .catch((error) => {
        if (error.name !== "AbortError") setState("error");
      });
    return () => controller.abort();
  }, [id, attempt]);
  return (
    <>
      <Link className="text-link back-link" to="/sessions">
        ← Volver a sesiones
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">REVISIÓN DE SESIÓN</span>
          <h1>Detalle de sesión</h1>
        </div>
      </div>
      {state === "loading" ? (
        <p role="status">Consultando sesión…</p>
      ) : state === "missing" ? (
        <EmptyState
          title="Sesión no encontrada"
          description="Este identificador no corresponde a una sesión. Puedes consultar las observaciones guardadas en la sección Manos."
        />
      ) : (
        <div className="panel error-state" role="alert">
          <h2>No se pudo consultar la sesión.</h2>
          <p>Comprueba la conexión con el backend.</p>
          <button
            className="button secondary"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Reintentar
          </button>
        </div>
      )}
    </>
  );
}

export function NotFound() {
  return (
    <EmptyState
      title="Esta página no está en la mesa."
      description="La dirección no existe. Puedes volver al panel en directo para continuar."
    />
  );
}
