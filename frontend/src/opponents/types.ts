import type { TournamentContext, TournamentSummary } from "../tournament/types";

export type Rate = {
  value: number | null;
  hits: number;
  opportunities: number;
  interval_95: [number, number] | null;
  confidence: string;
};
export type OpponentState = {
  observations?: Pick<
    NonNullable<OpponentState["analysis"]>,
    "coverage" | "event_sequence" | "timestamp" | "profiles"
  > | null;
  visibility: "training" | "internal_only";
  storage_error: string | null;
  analysis: {
    scope_id: string;
    revision: number;
    event_sequence: number;
    timestamp: number;
    coverage: string;
    context_valid: boolean;
    adaptive: {
      version: string;
      prior_strength: number;
      tournament: TournamentSummary | null;
      ranges: AdaptiveRange[];
    } | null;
    context: {
      hand_id: string;
      seats: number[];
      button_seat: number;
      tournament: TournamentContext | null;
    } | null;
    pending_showdowns: { hand_id: string; seats: number[] }[];
    profiles: {
      id: string;
      seat: number;
      nickname: string | null;
      active: boolean;
      hands: number;
      actions: number;
      stats: Record<
        | "vpip"
        | "pfr"
        | "three_bet"
        | "fold_to_three_bet"
        | "cbet"
        | "fold_to_cbet"
        | "wtsd",
        Rate
      > & {
        aggression_factor: {
          value: number | null;
          aggressive_actions: number;
          calls: number;
          reason: string | null;
          confidence: string;
        };
      };
    }[];
  } | null;
};

export type AdaptiveRange = {
  seat: number;
  prior: string;
  available_combos: number;
  effective_combos: number;
  status: string;
  top_classes: { hand: string; weight: number }[];
  last_update: {
    action: string;
    event_sequence: number;
    update: string;
    evidence: {
      statistic: string;
      opportunities: number;
      rate: number;
      data_weight: number;
      prior_weight: number;
      prior_source: {
        kind: "generic" | "tournament";
        label?: string;
        buy_in?: string;
        currency?: string;
      };
    };
  } | null;
};
