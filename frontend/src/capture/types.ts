import type { CardState } from "../cards/types";
import type { OcrState } from "../ocr/types";
import type { GameState } from "../game/types";
import type { EventStream } from "../events/types";
import type { HandTracking } from "../hands/types";
import type { PokerState } from "../poker/types";
import type { PreflopState } from "../preflop/types";
import type { OpponentState } from "../opponents/types";
import type { StrategyState } from "../strategy/types";
import type { DecisionState } from "../decisions/types";

export type PipelineMetrics = {
  active: boolean;
  window_seconds: number;
  capture_fps: number;
  processing_fps: number;
  queue_size: number;
  queue_capacity: number;
  queue_high_watermark: number;
  captured_frames: number;
  processed_frames: number;
  dropped_frames: number;
  discarded_frames: number;
  failed_frames: number;
  in_flight: number;
  processing_latency_ms: number | null;
  mean_processing_latency_ms: number | null;
  queue_wait_ms: number | null;
  frame_latency_ms: number | null;
};

export type CaptureStatus = {
  server_id: string;
  revision: number;
  capture_id: string | null;
  state: "idle" | "running" | "ended" | "stopped" | "error";
  source: "file" | "screen" | null;
  name: string | null;
  capture_fps: number;
  duration: number | null;
  error: string | null;
  hand_storage?: { kind: string; error: string | null };
  poker?: PokerState;
  preflop?: PreflopState;
  opponents?: OpponentState;
  strategy?: StrategyState;
  decisions?: DecisionState;
  evaluations?: { revision: number; storage_error: string | null };
  feedback?: {
    next_release: "HAND_FINISHED" | "SESSION_FINISHED";
    session_release: "HAND_FINISHED" | "SESSION_FINISHED" | null;
    revision: number;
    review_blocked: boolean;
  };
  pipeline: PipelineMetrics | null;
  observation_state: {
    recognition_available: boolean;
    observations_seen: number;
    last_frame_id: number | null;
    cards: CardState | null;
    ocr: OcrState | null;
    game_state: GameState | null;
    event_stream: EventStream | null;
    hands: HandTracking | null;
    actions?: {
      status: string;
      event_count: number;
      reason: string | null;
      pending_seat: number | null;
    };
  };
  frame: {
    frame_id: number;
    timestamp: number;
    fps: number;
    width: number;
    height: number;
  } | null;
};

export const emptyCapture: CaptureStatus = {
  server_id: "",
  revision: -1,
  capture_id: null,
  state: "idle",
  source: null,
  name: null,
  capture_fps: 5,
  duration: null,
  error: null,
  pipeline: null,
  observation_state: {
    recognition_available: false,
    observations_seen: 0,
    last_frame_id: null,
    cards: null,
    ocr: null,
    game_state: null,
    event_stream: null,
    hands: null,
  },
  frame: null,
};

export async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : `No se pudo completar la operación (${response.status}).`,
    );
  }
  return response.json() as Promise<T>;
}
