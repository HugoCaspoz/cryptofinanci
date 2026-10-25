import { useCallback, useEffect, useState } from "react";
import { regionEntries, type Region, type TableLayout } from "./types";

async function failure(response: Response) {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === "string"
    ? body.detail
    : "No se pudo guardar. Revisa las coordenadas del layout.";
}

export function useTableLayout() {
  const [layout, setLayout] = useState<TableLayout | null>(null);
  const [saved, setSaved] = useState("");
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [labels, setLabels] = useState(true);
  const [selected, setSelected] = useState("hero_cards");

  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/table-layout", {
        cache: "no-store",
        signal: signal
          ? AbortSignal.any([signal, AbortSignal.timeout(5000)])
          : AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error(await failure(response));
      const data: TableLayout = await response.json();
      if (signal?.aborted) return;
      setLayout(data);
      setSaved(JSON.stringify(data));
      setRevision(response.headers.get("ETag") || "");
    } catch (e) {
      if (!signal?.aborted)
        setError(
          e instanceof Error ? e.message : "No se pudo cargar el layout.",
        );
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function save() {
    if (!layout || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/table-layout", {
        method: "PUT",
        headers: { "Content-Type": "application/json", "If-Match": revision },
        body: JSON.stringify(layout),
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error(await failure(response));
      const data: TableLayout = await response.json();
      setLayout(data);
      setSaved(JSON.stringify(data));
      setRevision(response.headers.get("ETag") || "");
      setMessage(
        "Layout guardado. Se aplicará al iniciar la siguiente captura.",
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No se pudo guardar el layout.",
      );
    } finally {
      setBusy(false);
    }
  }

  function updateRegion(field: keyof Region, value: number) {
    setMessage("");
    setLayout((previous) => {
      if (!previous) return null;
      const next = structuredClone(previous);
      const entry = regionEntries(next).find((item) => item.key === selected);
      if (entry) entry.region[field] = value;
      next.calibrated = false;
      return next;
    });
  }

  function updateDetails(
    update: Partial<
      Pick<TableLayout, "platform" | "calibrated" | "card_profile">
    >,
  ) {
    setMessage("");
    setLayout((previous) =>
      previous ? { ...previous, calibrated: false, ...update } : null,
    );
  }

  function fitFrame(width: number, height: number) {
    if (!layout || width < 320 || height < 240 || width > 3840 || height > 2160)
      return;
    const next = structuredClone(layout);
    for (const { region } of regionEntries(next)) {
      region.x = Math.min(
        width - 1,
        Math.round((region.x * width) / layout.width),
      );
      region.y = Math.min(
        height - 1,
        Math.round((region.y * height) / layout.height),
      );
      region.width = Math.max(
        1,
        Math.min(
          width - region.x,
          Math.round((region.width * width) / layout.width),
        ),
      );
      region.height = Math.max(
        1,
        Math.min(
          height - region.y,
          Math.round((region.height * height) / layout.height),
        ),
      );
    }
    next.width = width;
    next.height = height;
    next.calibrated = false;
    setLayout(next);
    setMessage(
      "Regiones adaptadas. Revisa su posición y guarda antes de reiniciar la captura.",
    );
  }

  return {
    layout,
    busy,
    error,
    message,
    enabled,
    setEnabled,
    labels,
    setLabels,
    selected,
    setSelected,
    load,
    save,
    updateRegion,
    updateDetails,
    fitFrame,
    revision,
    dirty: layout !== null && JSON.stringify(layout) !== saved,
  };
}

export type LayoutEditorState = ReturnType<typeof useTableLayout>;
