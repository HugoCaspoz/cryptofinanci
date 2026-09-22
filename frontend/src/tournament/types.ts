export type TournamentPrior = {
  label: string;
  strength: number;
  vpip: number;
  pfr: number;
  three_bet: number;
};

export type TournamentContext = {
  buy_in: string;
  currency: string;
  tournament_type: "mtt" | "sit_and_go" | "satellite" | "bounty" | "other";
  starting_stack: number;
  players: number;
  remaining_players: number | null;
  prize_structure:
    { first_place: number; last_place: number; amount: string }[] | null;
  population_prior: TournamentPrior | null;
};

export type TournamentSummary = TournamentContext & {
  paid_places: number | null;
  prize_pool: string | null;
  prior_policy: string;
};

export const formats: Record<TournamentContext["tournament_type"], string> = {
  mtt: "Multimesa",
  sit_and_go: "Sit & Go",
  satellite: "Satélite",
  bounty: "Bounty",
  other: "Otro",
};
