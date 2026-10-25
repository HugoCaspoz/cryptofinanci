import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { parseEvent } from "./protocol";
import type { LiveEvent, Mode } from "./protocol";
import type { CaptureStatus } from "../capture/types";

type LiveState = {
  status: "connecting" | "connected" | "reconnecting";
  mode: Mode | null;
  events: LiveEvent[];
  latency: number | null;
  ping: () => void;
  captureSnapshot: CaptureStatus | null;
  captureReady: boolean;
  captureReceivedAt: number | null;
};

const LiveContext = createContext<LiveState | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<LiveState["status"]>("connecting");
  const [mode, setMode] = useState<Mode | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [latency, setLatency] = useState<number | null>(null);
  const sendPing = useRef<() => void>(() => {});
  const [delivery, setDelivery] = useState<{
    capture: CaptureStatus;
    receivedAt: number;
  } | null>(null);
  const captureSnapshot = delivery?.capture ?? null;
  const captureReceivedAt = delivery?.receivedAt ?? null;
  const [captureReady, setCaptureReady] = useState(false);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout>;
    let heartbeat: ReturnType<typeof setInterval>;
    let attempt = 0;
    let sentAt: number | null = null;
    let lastMessage = Date.now();

    function ping() {
      if (socket?.readyState === WebSocket.OPEN && sentAt === null) {
        sentAt = performance.now();
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }
    sendPing.current = ping;

    function connect() {
      if (disposed) return;
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${location.host}/ws/live`);
      const currentSocket = socket;
      let connectionId: string | null = null;
      let sequence = 0;
      lastMessage = Date.now();
      heartbeat = setInterval(() => {
        if (
          Date.now() - lastMessage > 15_000 ||
          (sentAt !== null && performance.now() - sentAt > 15_000)
        )
          socket?.close();
        else ping();
      }, 5_000);
      socket.onmessage = ({ data }) => {
        const receivedAt = performance.now();
        if (disposed || currentSocket !== socket || typeof data !== "string")
          return;
        const event = parseEvent(data);
        if (!event) return;
        if (connectionId === null) {
          if (event.type !== "system.ready") return;
          connectionId = event.connection_id;
        } else if (event.type === "system.ready") return;
        if (event.connection_id !== connectionId || event.sequence <= sequence)
          return;
        sequence = event.sequence;
        lastMessage = Date.now();
        if (event.type === "capture.snapshot") {
          setDelivery({ capture: event.payload.capture, receivedAt });
          setCaptureReady(true);
          return;
        }
        setEvents((previous) => [event, ...previous].slice(0, 40));
        if (event.type === "system.ready") {
          attempt = 0;
          setMode(event.payload.mode!);
          setStatus("connected");
          socket.send(JSON.stringify({ type: "capture.subscribe" }));
          ping();
        }
        if (event.type === "system.pong" && sentAt !== null) {
          setLatency(Math.round(performance.now() - sentAt));
          sentAt = null;
        }
      };
      socket.onerror = () => currentSocket.close();
      socket.onclose = () => {
        if (!disposed)
          void fetch("/api/auth/status")
            .then((r) => r.json())
            .then((auth) => {
              if (!disposed && auth.enabled && !auth.authenticated)
                window.location.assign("/login");
            })
            .catch(() => {});
        if (currentSocket !== socket) return;
        clearInterval(heartbeat);
        sentAt = null;
        if (disposed) return;
        setStatus("reconnecting");
        setLatency(null);
        setMode(null);
        setCaptureReady(false);
        retry = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10_000));
      };
    }
    connect();
    return () => {
      disposed = true;
      clearTimeout(retry);
      clearInterval(heartbeat);
      if (socket) {
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
      }
      sendPing.current = () => {};
    };
  }, []);

  return (
    <LiveContext.Provider
      value={{
        status,
        mode,
        events,
        latency,
        ping: () => sendPing.current(),
        captureSnapshot,
        captureReady,
        captureReceivedAt,
      }}
    >
      {children}
    </LiveContext.Provider>
  );
}

export function useLive() {
  const value = useContext(LiveContext);
  if (!value) throw new Error("LiveProvider is required");
  return value;
}
