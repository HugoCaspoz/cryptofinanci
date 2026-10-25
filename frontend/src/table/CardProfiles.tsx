import { useEffect, useState } from "react";
import type { LayoutEditorState } from "./useTableLayout";
import { readResponse } from "../capture/types";

type Profile = { id: string; name: string; platform: string };
export function CardProfiles({ editor }: { editor: LayoutEditorState }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/card-profiles", { signal: controller.signal })
      .then(readResponse<{ items: Profile[] }>)
      .then((data) => {
        if (!controller.signal.aborted) setProfiles(data.items);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      });
    return () => controller.abort();
  }, []);
  async function upload(file: File) {
    if (file.size > 16 * 1024 * 1024) {
      setError("El ZIP supera 16 MiB.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const data = await fetch("/api/card-profiles", {
        method: "POST",
        body,
      }).then(readResponse<Profile>);
      setProfiles((items) => [...items.filter((p) => p.id !== data.id), data]);
      editor.updateDetails({ card_profile: data.id, platform: data.platform });
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "No se pudo importar el perfil.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="panel session-panel">
      <h3>Perfil de cartas</h3>
      <label>
        Referencias visuales{" "}
        <select
          aria-label="Perfil de cartas"
          disabled={busy}
          value={editor.layout?.card_profile ?? ""}
          onChange={(e) => {
            const profile = profiles.find((p) => p.id === e.target.value);
            editor.updateDetails({
              card_profile: profile?.id ?? null,
              platform: profile?.platform ?? "Zeros demo",
            });
          }}
        >
          <option value="">Zeros demo · referencias sintéticas</option>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} · {p.platform}
            </option>
          ))}
        </select>
      </label>
      <label>
        Importar perfil ZIP{" "}
        <input
          aria-label="Importar perfil de cartas"
          type="file"
          accept=".zip"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = "";
          }}
        />
      </label>
      <p>
        ZIP de hasta 16 MiB con manifest.json y 52 imágenes (As.png, Kh.png,
        etc.) en la raíz. Cada imagen debe corresponder a esa plataforma y medir
        entre 32 y 1024 px. Guarda el layout y vuelve a iniciar la captura
        después de seleccionarlo.
      </p>
      {!editor.layout?.card_profile && (
        <p role="status">
          El perfil demo permite probar la app. Para tu sala necesitas
          referencias reales; la app no las genera automáticamente.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
