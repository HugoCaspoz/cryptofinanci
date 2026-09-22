import { regionEntries, validLayout, type Region } from "./types";
import type { LayoutEditorState } from "./useTableLayout";

export function LayoutPanel({ editor }: { editor: LayoutEditorState }) {
  const { layout, busy, error, message, enabled, labels, selected, dirty } =
    editor;
  const entries = layout ? regionEntries(layout) : [];
  const region = entries.find((item) => item.key === selected)?.region;
  const valid = layout !== null && validLayout(layout);
  return (
    <section
      className="panel layout-panel"
      aria-label="Configuración de la mesa"
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">MAPA DE LA MESA</span>
          <h2>Configuración de regiones</h2>
        </div>
        <span className="outline-badge">
          {layout?.calibrated
            ? "Calibración manual confirmada"
            : "Pendiente de calibración"}
        </span>
      </div>
      <p>
        Un layout de 1920 × 1080 y 6 asientos. Ajusta cada rectángulo sobre una
        captura de la mesa completa, sin bordes ni paneles adicionales.
      </p>
      <div className="layout-toggles">
        <label>
          <input
            type="checkbox"
            checked={enabled}
            disabled={!layout}
            onChange={(e) => editor.setEnabled(e.target.checked)}
          />{" "}
          Mostrar regiones
        </label>
        <label>
          <input
            type="checkbox"
            checked={labels}
            onChange={(e) => editor.setLabels(e.target.checked)}
          />{" "}
          Mostrar etiquetas
        </label>
        <span className="muted">
          29 regiones configuradas · No son detecciones automáticas
        </span>
      </div>
      {layout && region && (
        <fieldset disabled={busy} className="layout-fields">
          <label className="layout-platform">
            Plataforma
            <input
              maxLength={80}
              value={layout.platform}
              onChange={(e) =>
                editor.updateDetails({ platform: e.target.value })
              }
            />
          </label>
          <label className="layout-region">
            Región
            <select
              value={selected}
              onChange={(e) => editor.setSelected(e.target.value)}
            >
              {entries.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {(
            [
              ["x", "X"],
              ["y", "Y"],
              ["width", "Ancho"],
              ["height", "Alto"],
            ] as [keyof Region, string][]
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                step="1"
                min={key === "x" || key === "y" ? 0 : 1}
                max={key === "x" || key === "width" ? 1920 : 1080}
                value={Number.isFinite(region[key]) ? region[key] : ""}
                onChange={(e) =>
                  editor.updateRegion(key, e.target.valueAsNumber)
                }
              />
            </label>
          ))}
          <label className="layout-confirm">
            <input
              type="checkbox"
              checked={layout.calibrated}
              onChange={(e) =>
                editor.updateDetails({ calibrated: e.target.checked })
              }
            />{" "}
            He comprobado las 29 regiones sobre mi mesa.
          </label>
        </fieldset>
      )}
      {!valid && layout && (
        <p className="capture-error">
          Introduce un nombre y rectángulos con píxeles enteros dentro de 1920 ×
          1080.
        </p>
      )}
      <div className="layout-actions">
        <button
          className="button primary"
          disabled={busy || !valid || !dirty}
          onClick={() => void editor.save()}
        >
          Guardar layout
        </button>
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void editor.load()}
        >
          {dirty ? "Descartar cambios y recargar" : "Recargar layout"}
        </button>
        <span className="muted">
          {busy
            ? "Cargando…"
            : dirty
              ? "Cambios sin guardar · Overlay de borrador"
              : message || "Coordenadas en píxeles del frame original"}
        </span>
      </div>
      {error && (
        <p className="capture-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
