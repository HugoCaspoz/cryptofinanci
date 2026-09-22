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
      setMessage("Layout guardado.");
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
    update: Partial<Pick<TableLayout, "platform" | "calibrated">>,
  ) {
    setMessage("");
    setLayout((previous) =>
      previous ? { ...previous, calibrated: false, ...update } : null,
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
    dirty: layout !== null && JSON.stringify(layout) !== saved,
  };
}

export type LayoutEditorState = ReturnType<typeof useTableLayout>;
