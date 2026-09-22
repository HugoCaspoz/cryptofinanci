export type PokerEvent = {
  schema_version: number;
  sequence: number;
  scope_id: string;
  type: string;
  frame_id: number;
  timestamp: number;
  confidence: number | null;
  hand_id: string | null;
  player_id: string | null;
  amount: string | null;
  unit: string | null;
  action_evidence?: string[];
};

export type EventStream = {
  scope_id: string;
  event_count: number;
  first_sequence: number | null;
  dropped_events: number;
  capacity: number;
  events: PokerEvent[];
};
