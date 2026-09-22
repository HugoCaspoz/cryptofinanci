export type OcrField = {
  key: string;
  kind: "nickname" | "amount" | "blinds";
  value: string | null;
  unit: string | null;
  confidence: number;
  raw_text: string;
  latest_confidence: number;
  status: "waiting" | "pending" | "confirmed" | "unknown";
  confirmed_frame_id: number | null;
  confirmed_timestamp: number | null;
};

export type OcrState = {
  status: string;
  layout_revision: string | null;
  decimal_separator: string;
  last_sample_frame_id: number | null;
  last_sample_timestamp: number | null;
  fields: Record<string, OcrField>;
};
