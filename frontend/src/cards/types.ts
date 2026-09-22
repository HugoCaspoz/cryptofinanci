export type Card = {
  rank: string;
  suit: "spades" | "hearts" | "diamonds" | "clubs";
  confidence: number;
};

export type CardRegion = {
  cards: Card[];
  status:
    "waiting" | "pending" | "confirmed" | "empty" | "unknown" | "conflict";
  confirmations: number;
  required_confirmations: number;
};

export type CardState = {
  detector_status: string;
  profile: string | null;
  demo: boolean;
  layout_revision: string | null;
  hero: CardRegion;
  board: CardRegion;
  events: {
    id: number;
    type: string;
    frame_id: number;
    timestamp: number;
    cards: Card[];
  }[];
  event_count: number;
};

export const suits = { spades: "♠", hearts: "♥", diamonds: "♦", clubs: "♣" };
export const cardText = (card: Card) =>
  `${card.rank === "T" ? "10" : card.rank}${suits[card.suit]}`;
