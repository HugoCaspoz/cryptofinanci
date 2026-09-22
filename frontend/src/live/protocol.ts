import type { CaptureStatus } from "../capture/types";

export type Mode = "LIVE_REAL_MONEY" | "TRAINING";
export type LiveEvent = {
  version: 1;
  type: "system.ready" | "system.pong" | "system.error";
  connection_id: string;
  sequence: number;
  timestamp: string;
  payload: { mode?: Mode; code?: string };
};

export type CaptureEvent = Omit<LiveEvent, "type" | "payload"> & {
  type: "capture.snapshot";
  payload: { capture: CaptureStatus };
};

export function parseEvent(raw: string): LiveEvent | CaptureEvent | null {
  try {
    const event = JSON.parse(raw);
    if (
      !event ||
      event.version !== 1 ||
      ![
        "system.ready",
        "system.pong",
        "system.error",
        "capture.snapshot",
      ].includes(event.type) ||
      typeof event.connection_id !== "string" ||
      !Number.isInteger(event.sequence) ||
      event.sequence < 1 ||
      typeof event.timestamp !== "string" ||
      !Number.isFinite(Date.parse(event.timestamp)) ||
      !event.payload ||
      typeof event.payload !== "object"
    )
      return null;
    if (
      event.type === "system.ready" &&
      !["LIVE_REAL_MONEY", "TRAINING"].includes(event.payload.mode)
    )
      return null;
    if (event.type === "capture.snapshot") {
      const capture = event.payload.capture;
      if (
        !capture ||
        typeof capture.server_id !== "string" ||
        !capture.server_id ||
        !Number.isInteger(capture.revision) ||
        capture.revision < 0 ||
        !["idle", "running", "ended", "stopped", "error"].includes(
          capture.state,
        ) ||
        !(
          capture.capture_id === null || typeof capture.capture_id === "string"
        ) ||
        !capture.observation_state?.game_state ||
        !Array.isArray(capture.observation_state.game_state.players) ||
        !Array.isArray(capture.observation_state.event_stream?.events)
      )
        return null;
      return event as CaptureEvent;
    }
    return event as LiveEvent;
  } catch {
    return null;
  }
}
