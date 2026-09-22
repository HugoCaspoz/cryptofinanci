export type StrategyAction =
  "FOLD" | "CHECK" | "CALL" | "BET" | "RAISE" | "ALL_IN";

export type StrategyConfig = {
  bet_sizes: number[];
  raise_multiplier: number;
  temperature: number;
  tournament_adjustment: boolean;
};

export type StrategyOption = {
  action: StrategyAction;
  sizing_pot: number | null;
  added_bb: number | null;
  total_bb: number | null;
  all_in: boolean;
  frequency: number;
  ev_bb: number | null;
  fold_probability?: number;
  range_fold_probability?: number;
  balanced_fold_probability?: number;
  equity_when_called?: number;
};

export type Strategy = {
  basis: string;
  equity: number | null;
  options: StrategyOption[];
  summary: Partial<Record<StrategyAction, number>>;
};

export type StrategyResult = {
  version: string;
  status: "ready" | "waiting" | "unavailable";
  reason: string;
  hand_id: string | null;
  street: string;
  timestamp: number | null;
  analysis_latency_ms?: number;
  decision: {
    street: string;
    position?: string | null;
    villain_seat?: number;
    pot_bb?: number;
    to_call_bb?: number;
    required_equity?: number | null;
    spr?: number | null;
    risk_factor?: number;
    effective_stack_bb?: number | null;
  } | null;
  baseline_strategy: Strategy | null;
  exploitative_strategy: Strategy | null;
  adjustments: {
    input: string;
    applied: boolean;
    reason?: string;
    basis?: string;
    statistic?: string | null;
    hits?: number;
    opportunities?: number;
    data_weight?: number;
    baseline?: { effective_combos: number; equity: number };
    exploit?: { effective_combos: number; equity: number };
  }[];
  bluff: BluffAnalysis | null;
  tournament: {
    stage: string;
    risk_factor: number;
    paid_places: number | null;
    remaining_players: number | null;
    applied: boolean;
    average_stack_estimate: number | null;
  } | null;
};

export type StrategyState = {
  status: string;
  visibility: "training" | "internal_only";
  config: StrategyConfig;
  storage_error: string | null;
  result: StrategyResult | null;
};

export type CardEffect = {
  card: string;
  continuing_removed: number;
  folding_removed: number;
  random_card_reference: number;
};

export type BluffCase = {
  applicable: boolean;
  bluff_candidate: boolean;
  classification: "value" | "bluff" | "semi_bluff" | null;
  reason: string;
  recommended_sizing?: {
    action: StrategyAction;
    sizing_pot: number | null;
    added_bb: number;
    total_bb: number;
    all_in: boolean;
  };
  estimated_fold_frequency?: number;
  range_fold_frequency?: number;
  required_fold_frequency?: number;
  fold_shift_from_blockers?: number;
  equity_when_called?: number;
  ev_gain_bb?: number;
  passive_action?: StrategyAction;
  bluff_frequency?: number;
  commitment?: number;
  fold_source?: { statistic: string | null; opportunities?: number };
};

export type RangeView = {
  hero_equity: number;
  range_advantage: string;
  nut_advantage_proxy: string;
} | null;

export type BluffAnalysis = {
  version: string;
  applicable: boolean;
  bluff_candidate: boolean;
  reason: string;
  recommended_sizing?: BluffCase["recommended_sizing"];
  estimated_fold_frequency?: number;
  blockers?: CardEffect[];
  unblockers?: CardEffect[];
  showdown_value?: { equity: number; category: string; hand: string };
  draws?: {
    completion_count: number;
    flush: boolean;
    straight: string | null;
    backdoor: boolean;
  };
  board_texture?: { texture: string; pairing: string; high_card: string };
  spr?: number | null;
  player_tendencies?: {
    seat: number;
    statistics: Record<
      string,
      { hits: number; opportunities: number; rate: number; data_weight: number }
    >;
  };
  range_advantage?: { baseline: RangeView; exploit: RangeView };
  baseline_strategy?: BluffCase;
  exploit_strategy?: BluffCase;
};
