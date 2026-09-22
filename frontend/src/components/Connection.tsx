import { useLive } from "../live/LiveProvider";

export function Connection() {
  const { status } = useLive();
  const text = {
    connected: "Backend conectado",
    connecting: "Conectando…",
    reconnecting: "Reconectando…",
  }[status];
  return (
    <span className={`connection ${status}`} role="status">
      <i />
      {text}
    </span>
  );
}
