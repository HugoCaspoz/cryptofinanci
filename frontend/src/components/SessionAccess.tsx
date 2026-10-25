import { useEffect, useState } from "react";

export function SessionAccess() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/auth/status", { signal: controller.signal })
      .then((r) => r.json())
      .then((data) => {
        if (!controller.signal.aborted) setEnabled(data.enabled === true);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return enabled ? (
    <form method="post" action="/api/auth/logout">
      <button className="button secondary">Salir</button>
    </form>
  ) : null;
}
