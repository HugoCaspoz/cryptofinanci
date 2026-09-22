export type HandSummary = {
  hand_id: string;
  scope_id: string;
  number: number;
  status: "active" | "finished" | "incomplete";
  started_timestamp: number;
  finished_timestamp: number | null;
  partial_start: boolean;
  reason: string | null;
  context?: { name: string; mode: string };
};
export type HandTracking = {
  active_hand: HandSummary | null;
  started_count: number;
  finished_count: number;
  boundary_pending: boolean;
  recent: HandSummary[];
};
export const handLabels = {
  active: "En curso",
  finished: "Terminada",
  incomplete: "Incompleta",
  unidentified: "Esperando cartas",
};
