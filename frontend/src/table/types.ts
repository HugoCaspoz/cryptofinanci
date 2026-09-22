export type Region = { x: number; y: number; width: number; height: number };
export type TableLayout = {
  version: 1;
  platform: string;
  width: 1920;
  height: 1080;
  calibrated: boolean;
  regions: Record<
    "hero_cards" | "board" | "pot" | "dealer_button" | "blinds",
    Region
  >;
  players: Record<"nickname" | "stack" | "bet" | "action", Region>[];
};

export function regionEntries(layout: TableLayout) {
  return [
    ...Object.entries(layout.regions).map(([key, region]) => ({
      key,
      label: key,
      region,
    })),
    ...layout.players.flatMap((player, i) =>
      Object.entries(player).map(([key, region]) => ({
        key: `players.${i}.${key}`,
        label: `P${i + 1} · ${key}`,
        region,
      })),
    ),
  ];
}

export function validLayout(layout: TableLayout) {
  return (
    layout.platform.trim().length > 0 &&
    layout.platform.length <= 80 &&
    regionEntries(layout).every(
      ({ region: r }) =>
        Object.values(r).every(Number.isInteger) &&
        r.x >= 0 &&
        r.y >= 0 &&
        r.width > 0 &&
        r.height > 0 &&
        r.x + r.width <= layout.width &&
        r.y + r.height <= layout.height,
    )
  );
}
