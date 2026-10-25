export type LatencySummary = {
  last_ms: number | null;
  mean_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
  samples: number;
  total_samples: number;
  frame_id: number | null;
  target_ms: number | null;
  within_target: boolean | null;
};

export class LatencyWindow {
  private values: number[] = [];
  private count = 0;
  add(value: number, frameId: number | null): LatencySummary | null {
    if (!Number.isFinite(value) || value < 0) return null;
    this.values.push(value);
    if (this.values.length > 128) this.values.shift();
    this.count++;
    const sorted = [...this.values].sort((a, b) => a - b);
    const p95 = sorted[Math.ceil(sorted.length * 0.95) - 1];
    return {
      last_ms: value,
      mean_ms: sorted.reduce((a, b) => a + b, 0) / sorted.length,
      p95_ms: p95,
      max_ms: sorted.at(-1)!,
      samples: sorted.length,
      total_samples: this.count,
      frame_id: frameId,
      target_ms: 100,
      within_target: p95 < 100,
    };
  }
}
