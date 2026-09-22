export type PriorAction = {
  seat: number;
  action: string;
  total_bb?: string | number | null;
};
export type PreflopConfig = {
  hand_id: string;
  hero_seat: number;
  button_seat: number;
  seats: number[];
  ante_total_bb: string;
  pot_includes_bets: boolean;
  history_confirmed: boolean;
  prior_actions: PriorAction[];
  rules: Record<string, unknown>[];
};
export type PreflopState = {
  status: string;
  visibility: "training" | "internal_only";
  config: PreflopConfig | null;
  result: {
    status: "ready" | "unavailable";
    reason: string;
    action: "FOLD" | "CHECK" | "CALL" | "RAISE" | "ALL_IN" | null;
    sizing_bb: number | null;
    additional_bb: number | null;
    confidence: null;
    rule_id: string | null;
    timestamp: number | null;
    context: {
      position?: string;
      effective_stack_bb?: number;
      scenario?: string;
      players_dealt?: number;
    };
  } | null;
};
