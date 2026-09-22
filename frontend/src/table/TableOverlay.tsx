import { regionEntries, validLayout } from "./types";
import type { LayoutEditorState } from "./useTableLayout";

export function TableOverlay({
  editor,
  width,
  height,
}: {
  editor: LayoutEditorState;
  width: number;
  height: number;
}) {
  const { layout, enabled, labels, selected } = editor;
  if (!layout || !enabled) return null;
  if (width !== layout.width || height !== layout.height)
    return (
      <span className="layout-mismatch">
        Overlay oculto: captura {width} × {height}. Se requieren 1920 × 1080.
      </span>
    );
  if (!validLayout(layout))
    return (
      <span className="layout-mismatch">
        Overlay oculto: revisa las coordenadas.
      </span>
    );
  return (
    <svg
      className="table-overlay"
      role="img"
      aria-label="Regiones configuradas de la mesa"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {regionEntries(layout).map(({ key, label, region: r }) => (
        <g
          key={key}
          data-region={key}
          className={
            selected === key
              ? "selected"
              : key.startsWith("players.")
                ? "player-region"
                : "table-region"
          }
        >
          <rect
            x={r.x}
            y={r.y}
            width={r.width}
            height={r.height}
            vectorEffect="non-scaling-stroke"
          />
          {labels && (
            <text x={r.x + 5} y={r.y + Math.min(24, r.height - 3)}>
              {label}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
