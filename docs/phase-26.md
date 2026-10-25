# Fase 26 — Muestreo inteligente

## Revisión y resultado

Se revisaron la cola limitada, los adaptadores de captura y las métricas de la fase 25. El OCR era la etapa más costosa. El nuevo filtro visual decide qué frames llegan a visión, antes de ejecutar cartas, OCR, acciones, reconstrucción y preparación del JPEG.

En `/live`, «FPS de captura» ofrece **Inteligente: 2 / 10 FPS**, seleccionado inicialmente, junto a los FPS fijos anteriores. En reposo el objetivo es 2 FPS. Un cambio visual activa hasta 10 FPS durante dos segundos de tiempo de fuente; cada cambio posterior renueva ese plazo. Al terminar vuelve a 2 FPS. El primer frame siempre se admite y cada captura reinicia sus contadores y referencias. El calendario mantiene una media de 2 FPS también con vídeos nativos de 5 FPS, sin duplicarlos ni acumular muestras atrasadas.

## Detección y límites de memoria

La lectura se solicita a 10 FPS en modo inteligente. El worker de captura compara firmas de 64 × 32 píxeles en escala de grises de cartas de Hero, board, pot, botón, stacks, apuestas y acciones. Usa el layout congelado de esa captura. Un cambio de intensidad superior a 20 en al menos el 2,5 % de una región activa la ráfaga. Con resolución incompatible o sin layout, compara una firma de la imagen completa. Las zonas ajenas a las regiones no activan el detector cuando hay un layout compatible.

Solo conserva las firmas anteriores, nunca una colección de frames. La comparación ocurre en el worker de captura, separado del event loop y del worker de visión. La cola conserva su capacidad, política de frame más reciente y protección frente a procesadores lentos.

`pipeline.sampling` expone `mode`, `target_fps` y, en modo adaptativo, `observed_frames`, `skipped_frames` y `burst_seconds`. «Depuración del pipeline» muestra el objetivo actual y los frames omitidos. Los FPS y `captured_frames` existentes cuentan los frames admitidos al procesamiento; `observed_frames` cuenta las imágenes únicas inspeccionadas por el filtro y `skipped_frames` las omitidas antes de la cola. Los descartes por sobrecarga o parada siguen contabilizados por separado. En una captura terminada normalmente: `observed_frames = captured_frames + skipped_frames`.

## API y compatibilidad

- `POST /api/capture/file`: campo de formulario `sampling_mode=adaptive`.
- `POST /api/capture/screen`: JSON con `sampling_mode: "adaptive"`.
- Solo se admiten `fixed` y `adaptive`. El valor predeterminado de la API sigue siendo `fixed` para conservar sus clientes existentes.
- En modo adaptativo, el adaptador usa 10 FPS independientemente del `capture_fps` válido recibido. El navegador comparte y envía imágenes a ese ritmo máximo, manteniendo una sola subida en curso. `capture_fps` y `frame.fps` representan el ritmo configurado del adaptador; el objetivo de análisis está en `pipeline.sampling.target_fps`.

No cambia las confirmaciones temporales de OCR/acciones, las instantáneas inmutables, los permisos de revisión ni el explicador de OpenAI con respaldo local.

## Archivos

- `backend/app/pipeline_engine/sampling.py`: detector y calendario.
- `backend/app/pipeline_engine/pipeline.py`: filtro antes de la cola y telemetría.
- `backend/app/capture_engine/source.py` y `routes.py`: modo de fuente y contratos HTTP.
- `frontend/src/capture/{CaptureControls,CaptureProvider,PipelineDebug,types}`: selector, envío y estado visible.
- `backend/tests/test_sampling.py`, `test_latency.py` y `frontend/tests/sampling.spec.ts`: cobertura. La prueba de latencias permite que la lectura, independiente, esté por delante del frame procesado.
- Versiones en `backend/app/version.py`, `backend/tests/test_api.py`, `frontend/src/App.tsx` y `pages/Dashboard.tsx`; README y esta documentación.

## Ejecución y pruebas

Arrancar con `docker compose up --build -d --wait` y abrir `http://localhost:5173/live`. Mantener «Inteligente: 2 / 10 FPS», reproducir un archivo o compartir una ventana y abrir «Depuración del pipeline». Sobre una escena quieta el objetivo es 2; al cambiar la mesa pasa a 10 y vuelve a 2 tras dos segundos sin cambios. También se puede seleccionar un ritmo fijo.

Pruebas específicas: `python -m pytest backend/tests/test_sampling.py backend/tests/test_pipeline.py backend/tests/test_latency.py -q` desde la raíz. Construcción y formato del cliente: `npm.cmd run build` y `npm.cmd run format:check` desde `frontend`.

La regresión del backend se ejecutó en Docker con Tesseract y una base PostgreSQL exclusiva de pruebas. El navegador se probó con Edge y dos contenedores auxiliares aislados, sin introducir manos de prueba en la base principal. Para repetir el navegador, preparar el backend con `python scripts/seed_timeline_review.py --serve` desde la imagen de tests y una interfaz apuntando a él; configurar `E2E_BASE_URL=http://127.0.0.1:5174`, `E2E_BROWSER_CHANNEL=msedge`, `LATENCY_E2E=1` y `TIMELINE_E2E=1`, y ejecutar:

```powershell
node node_modules/@playwright/test/cli.js test tests/app.spec.ts tests/latency.spec.ts tests/timeline.spec.ts tests/sampling.spec.ts --workers=1
```

El escenario de entrenamiento se ejecuta aparte con `playwright.training.config.ts` y `training-tests/strategy.spec.ts`, usando `sample_data/opponents-demo.avi` generado dentro de Docker con `--decision-hold-seconds 4` como se describe en la fase 25. Comprueba la estrategia durante el turno, su archivo, evaluación y explicación, ahora con el modo inteligente predeterminado.

El filtro sobre 100 frames estáticos a 10 FPS admite 20 y omite 80. Es una reducción del 80 % de las entradas a visión frente a analizar esos 100 frames, no una reducción medida del 80 % de CPU total. Las pruebas cubren ruido leve, cambios de ROI, exclusión del fondo, fin de ráfaga, nuevo cambio, fuentes de 5 FPS, reinicio y contabilidad de la cola.

Resultado final: **595 pruebas de backend correctas**, incluidas las de PostgreSQL; **10 pruebas de navegador correctas** en los cuatro archivos indicados y **1 escenario de entrenamiento correcto**. Construcción TypeScript/Vite, formato y `git diff --check` correctos. Quedan dos avisos de deprecación de las dependencias de TestClient. Los otros escenarios de `tests/capture.spec.ts` requieren sus vídeos de fixture adicionales y no forman parte de esta selección de navegador.

En la última reproducción de entrenamiento: 312 frames inspeccionados, 116 omitidos antes de visión (37,2 %), 196 admitidos, 195 procesados y 1 descartado por la cola; máximo de cola 2/2. Se comprobó la revisión de la decisión y su explicación. Son observaciones de una demo con vídeo nativo de 5 FPS y carga concreta, no una garantía para otras mesas ni una comparación controlada de CPU con la fase anterior. Los contenedores auxiliares se detuvieron al terminar. La instancia principal quedó saludable en fase 26, modo `LIVE_REAL_MONEY` y PostgreSQL.

## Limitaciones y siguiente fase

La captura, decodificación y, en pantalla, codificación/subida siguen trabajando hasta 10 FPS: el ahorro está después del filtro. Un vídeo de 5 FPS no produce diez imágenes únicas por segundo. La CPU, el navegador y la cola pueden reducir el ritmo real por debajo del objetivo; 10 FPS no garantiza diez análisis completos por segundo.

El detector usa diferencias visuales con umbrales fijos, no entiende que haya ocurrido una acción de poker. Animaciones o ruido fuerte pueden prolongar la ráfaga; cambios pequeños, graduales o de color con igual intensidad pueden pasar inadvertidos. La muestra periódica de reposo sigue ejecutando la visión completa. Los umbrales necesitan validación con mesas reales y layouts calibrados. La firma global de respaldo es menos sensible a cambios pequeños.

La fase 27 añadirá un buffer circular de los últimos 10–30 segundos de frames. Esta fase no almacena ese historial.
