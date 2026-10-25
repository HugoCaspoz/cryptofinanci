import type { GameState } from "../game/types";
import type { PokerEvent } from "../events/types";

export type DecisionSummary = {
  id: string;
  hand_id: string;
  hero_seat: number;
  frame_id: number;
  timestamp: number;
  event_sequence: number;
  street: string;
  action_count: number;
  history_complete: boolean;
  strategy_input_available: boolean;
  frame_available?: boolean;
  evaluation_status?: string;
  actual_action?: { action: string } | null;
  ev_difference_bb?: number | null;
};
export type DecisionState = {
  visibility: "training" | "internal_only";
  count: number;
  pending: number;
  storage_error: string | null;
  reason: string;
  recent: DecisionSummary[];
  active_id: string | null;
};
type Pool = [number, [[string, string], number][]];
export type DecisionDetail = Omit<
  DecisionSummary,
  "street" | "action_count"
> & {
  source_event_sequence: number;
  actions: PokerEvent[];
  request: {
    state: Pick<
      GameState,
      | "hero_cards"
      | "board"
      | "pot"
      | "pot_unit"
      | "street"
      | "players"
      | "small_blind"
      | "big_blind"
      | "blinds_unit"
      | "current_player"
    >;
    decision: {
      exploit_pools: Pool[];
      neutral_pools: Pool[];
      counts: [number, [string, number, number][]][];
    } | null;
  };
};
