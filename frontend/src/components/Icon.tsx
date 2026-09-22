type Name =
  | "dashboard"
  | "live"
  | "sessions"
  | "arrow"
  | "shield"
  | "activity"
  | "video"
  | "check"
  | "cards";
const paths: Record<Name, string> = {
  dashboard: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  live: "M3 5h18v13H3z M8 22h8 M12 18v4 M10 9l5 3-5 3z",
  sessions: "M4 4h16v17H4z M8 2v4 M16 2v4 M8 10h8 M8 14h5",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
  activity: "M2 12h5l3-8 4 16 3-8h5",
  video: "M3 5h13v14H3z M16 10l5-3v10l-5-3",
  check: "M5 12l4 4L19 6",
  cards: "M7 3h13v17H7z M4 6H2v16h13 M13.5 7l3 4-3 4-3-4z",
};
export function Icon({ name, size = 20 }: { name: Name; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
