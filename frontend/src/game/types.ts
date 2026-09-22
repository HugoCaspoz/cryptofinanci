export type FieldEvidence = {
  status: string;
  confidence: number;
  confirmed_frame_id: number | null;
  confirmed_timestamp: number | null;
  layout_revision: string | null;
};

export type PlayerState = {
  player_id: string;
  seat: number;
  nickname: string | null;
  position: string | null;
  stack: string | null;
  stack_unit: string | null;
  current_bet: string | null;
  bet_unit: string | null;
  folded: boolean | null;
  all_in: boolean | null;
};

export type GameState = {
  scope_id: string;
  hand_id: string | null;
  hand_status: "unidentified" | "active" | "finished" | "incomplete";
  street: "unknown" | "preflop" | "flop" | "turn" | "river";
  pot: string | null;
  pot_unit: string | null;
  board: string[];
  hero_cards: string[];
  players: PlayerState[];
  current_player: string | null;
  button_position: number | null;
  small_blind: string | null;
  big_blind: string | null;
  blinds_unit: string | null;
  revision: number;
  frame_id: number | null;
  timestamp: number | null;
  evidence: Record<string, FieldEvidence>;
  events: {
    id: number;
    type: "GAME_STATE_UPDATED";
    revision: number;
    frame_id: number;
    timestamp: number;
    changes: { field: string; previous: unknown; current: unknown }[];
  }[];
};
