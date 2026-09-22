export type PokerConfig = {
  range_source?: "manual" | "adaptive";
  hero_seat: number | null;
  opponents: { seat: number; range: string }[];
  pot_includes_bets: boolean | null;
  samples: number;
  seed: number;
  postflop_context?: {
    hand_id: string;
    hero_range: string | null;
    button_seat: number | null;
  } | null;
};

export type PokerState = {
  config: PokerConfig;
  status: "unconfigured" | "pending" | "ready" | "error";
  visibility: "training" | "internal_only";
  analysis: {
    range_source: "manual" | "adaptive";
    range_provenance: {
      version: string;
      event_sequence: number;
      timestamp: number;
    } | null;
    hand_id: string | null;
    hero_seat: number;
    frame_id: number | null;
    timestamp: number | null;
    warnings: string[];
    postflop: PostflopAnalysis | null;
    metrics: {
      pot_size: string | null;
      unit: string | null;
      effective_stack: string | null;
      effective_unit?: string | null;
      effective_by_seat: { seat: number; stack: string }[];
      spr: number | null;
      to_call: string | null;
      to_call_unit?: string | null;
      pot_odds: number | null;
      required_equity: number | null;
    } | null;
    equity: {
      method: "monte_carlo" | "exact_river_heads_up";
      equity: number;
      samples: number;
      interval_95: [number, number];
      ranges: { seat: number; range: string; available_combos: number }[];
    } | null;
  } | null;
};

export type PostflopAnalysis = {
  hand_strength: {
    category: string;
    detail: string;
    plays_board: boolean;
    minimum_hole_cards_used: number;
  };
  draws: {
    flush: { count: number; cards: string[]; suit: string } | null;
    straight: { kind: string; count: number; cards: string[] } | null;
    backdoor_flush_suits: string[];
    backdoor_straight: boolean;
    completion_count: number;
    completion_cards: string[];
  };
  board_texture: {
    pairing: string;
    suit_pattern: number[];
    texture: string;
    high_card: string;
    ranks_in_straight_window: number;
  };
  position: {
    relative: string;
    action_order: number[];
    button_seat: number;
  } | null;
  bet_sizing: {
    street_start_pot: string;
    unit: string | null;
    by_seat: { seat: number; amount: string; pot_fraction: number }[];
  } | null;
  range_comparison: {
    hero_equity: number;
    interval_95: [number, number];
    samples: number;
    method: string;
    range_advantage: string;
    nut_advantage_proxy: string;
    hero: { current_nuts_fraction: number; available_combos: number };
    opponent: { current_nuts_fraction: number; available_combos: number };
  } | null;
  warnings: string[];
};
