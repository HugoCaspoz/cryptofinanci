# Fase 27 — Buffer temporal

## Revisión de la fase anterior y resultado

Se revisaron el muestreo adaptativo de la fase 26, sus dos workers y la política de la cola. El historial se guarda **antes** del filtro y de la cola: permite recuperar también una imagen omitida por el muestreo o descartada por sobrecarga del reconocimiento.

Cada captura tiene un buffer circular en memoria de los últimos **10 segundos de tiempo de fuente**, configurable entre 10 y 30 mediante `FRAME_BUFFER_SECONDS`. Se retienen imágenes JPEG de calidad 85 a la resolución original, con ID, timestamp, ancho y alto. No se mantienen arrays BGR ni vistas de sus píxeles. El buffer aplica simultáneamente tres límites: tiempo, **450 frames** y **64 MiB de JPEG**. Al exceder cualquiera, elimina las imágenes más antiguas. Los límites de cantidad y bytes pueden acortar la ventana disponible.

La compresión se ejecuta en el worker de captura. Una consulta toma referencias a bytes inmutables bajo un lock breve; no ejecuta visión ni reconstrucción y no bloquea el event loop con codificación. Un fallo de codificación se contabiliza sin detener el análisis de esa imagen. IDs repetidos, timestamps no finitos o muestras fuera de orden no se incorporan.

## Consulta de un evento detectado tarde

Usar el ID de la captura y el timestamp de fuente del evento. `GET /api/capture/{capture_id}/buffer/frame?timestamp=12.345` devuelve el último frame conservado cuyo timestamp es **menor o igual** al solicitado. Nunca escoge una imagen posterior. Un instante anterior al inicio retenido o posterior al último frame devuelve 404. Los encabezados indican el ID y timestamp realmente elegidos; no se afirma que exista una muestra exacta en todos los instantes.

Para localizar y recuperar una imagen concreta:

- `GET /api/capture/{capture_id}/buffer`: índice de metadatos ordenado por tiempo, sin JPEG ni análisis.
- `GET /api/capture/{capture_id}/buffer/frames/{frame_id}`: JPEG del ID exacto. Si ya salió del buffer, 404.
- Las respuestas correctas llevan `Cache-Control: no-store`; los JPEG incluyen `X-Frame-Id`, `X-Frame-Timestamp`, `X-Frame-Width` y `X-Frame-Height`.
- Una captura anterior devuelve 409 al iniciar otra. El buffer nuevo empieza vacío. Al detener o alcanzar EOF se conserva la última ventana para inspeccionarla; no envejece por reloj de pared. Al cerrar el motor se libera.

`pipeline.buffer` publica ventana configurada, frames y bytes retenidos, límites, extremos temporales, expulsiones y errores de codificación. No envía imágenes por WebSocket. Los contadores y FPS del pipeline y del muestreo conservan su significado anterior.

## Interfaz

En `/live`, abrir **Historial temporal de imágenes**, pulsar **Actualizar historial** y mover **Frame del historial**. Se muestra el ID, tiempo de fuente y resolución de la imagen elegida. La lista se actualiza a petición del usuario: durante la captura, una imagen puede caducar antes de seleccionarla; en ese caso se pide actualizar el historial. Cambiar de captura reinicia la selección y retira la imagen anterior. El visor es independiente de la vista en directo y del estado de partida.

El historial contiene imágenes de la fuente, como la vista en directo. No ofrece análisis estratégico adicional, no vuelve a ejecutar OCR, no modifica eventos ni decisiones y no incorpora información posterior a una instantánea. La atribución automática de imágenes a eventos atrasados y la corrección retroactiva de acciones no se implementan en esta fase: quedan disponibles las consultas por identidad y tiempo que permiten localizar las imágenes conservadas.

## Archivos principales

- `backend/app/pipeline_engine/temporal_buffer.py`: almacenamiento, límites y búsquedas.
- `backend/app/pipeline_engine/pipeline.py`: registro antes del muestreo y telemetría.
- `backend/app/capture_engine/engine.py`, `routes.py`: ciclo de vida y consultas HTTP.
- `backend/app/config.py`, `main.py`, `.env.example` y `compose.yaml`: configuración de la ventana.
- `frontend/src/capture/FrameHistory.tsx`, `types.ts` y `pages/Live.tsx`: visor y contratos.
- `backend/tests/test_temporal_buffer.py` y `frontend/tests/history.spec.ts`: pruebas del buffer y visor.
- Versión 0.27 en servidor, prueba de API, App y Dashboard; README y este documento.

## Cómo ejecutar y probar

Ejecutar `docker compose up --build -d --wait` y abrir `http://localhost:5173/live`. Para ampliar la ventana, definir por ejemplo `FRAME_BUFFER_SECONDS=30` en `.env` y volver a ejecutar Compose. El valor se valida al arrancar y no se cambia desde el navegador.

Desde la raíz, pruebas específicas:

```powershell
python -m pytest backend/tests/test_temporal_buffer.py backend/tests/test_sampling.py backend/tests/test_pipeline.py backend/tests/test_latency.py backend/tests/test_capture.py -q
```

La regresión completa usa Docker, Tesseract y una base PostgreSQL exclusiva para pruebas mediante `HAND_TEST_POSTGRES`. No se introducen manos sintéticas en la instancia principal. Para el navegador, levantar el backend auxiliar con `python scripts/seed_timeline_review.py --serve` desde la imagen de pruebas y su interfaz en el puerto 5174. En `frontend`, definir `E2E_BASE_URL=http://127.0.0.1:5174`, `E2E_BROWSER_CHANNEL=msedge`, `LATENCY_E2E=1` y `TIMELINE_E2E=1`, y ejecutar:

```powershell
node node_modules/@playwright/test/cli.js test tests/app.spec.ts tests/latency.spec.ts tests/timeline.spec.ts tests/sampling.spec.ts tests/history.spec.ts --workers=1
```

El escenario `training-tests/strategy.spec.ts` se ejecuta aparte con `playwright.training.config.ts` y el vídeo `opponents-demo.avi` de la fase 25. Se comprueba que la codificación adicional del historial conviva con la estrategia, el archivo de la decisión, su evaluación y la explicación.

Las pruebas del buffer verifican fronteras temporales, consulta sin futuro, expulsión por bytes y cantidad, ausencia de referencias a arrays originales, JPEG a resolución original, errores de codificación, muestras desordenadas, imágenes omitidas por el muestreo y descartadas por la cola, respuestas HTTP y separación de capturas. El navegador comprueba selección, imagen real, ausencia de reanálisis, frame caducado, reinicio y ausencia de desbordamiento en escritorio y móvil. También se ejecutan la compilación TypeScript/Vite, Prettier y `git diff --check`.

Resultado: **603 pruebas de backend correctas**, incluidas las de PostgreSQL; los **11 escenarios de navegador** seleccionados y **1 escenario de entrenamiento**, correctos. La prueba de latencias necesitó precisar el selector de su captura de pantalla al existir dos paneles con el estilo compartido; su repetición pasó. Los otros casos de `tests/capture.spec.ts` requieren sus vídeos adicionales y no se incluyen en esta selección. Solo quedan dos avisos de deprecación de las dependencias de TestClient.

En la demo de entrenamiento, al detenerla se conservaron **51 frames**, desde **52,4 hasta 62,4 segundos**, con **4.588.143 bytes de JPEG**; 262 imágenes habían salido del buffer y no hubo fallos de codificación. El muestreo inspeccionó 313 frames y omitió 116 antes del reconocimiento; el historial conservó también esas imágenes mientras estuvieron dentro de la ventana. El máximo de cola fue 2/2 y se completaron estrategia, archivo, evaluación y explicación. Son datos de una reproducción concreta de vídeo a 5 FPS, no un benchmark de otras mesas.

La aplicación principal quedó saludable en fase 27, modo `LIVE_REAL_MONEY` y PostgreSQL. Los contenedores auxiliares se detuvieron después de las comprobaciones.

## Limitaciones y siguiente fase

El buffer conserva las imágenes que el adaptador entrega: no recupera frames nunca capturados, reemplazados en la entrada de pantalla o ausentes en un vídeo de pocos FPS. JPEG es compresión con pérdida, a resolución original; no equivale a conservar exactamente cada píxel BGR. No hay reproducción continua ni historial persistente después de reiniciar el servidor.

La compresión añade CPU y puede reducir el ritmo real de captura. Los 64 MiB limitan los JPEG retenidos, no toda la memoria del proceso ni sus arrays de trabajo. La ventana usa timestamps de fuente: al pausar o detenerse el vídeo no avanza por reloj de pared. Este buffer no promete que toda acción pueda reconstruirse retrospectivamente ni que el frame del evento siga disponible cuando llegue una confirmación muy tardía.

La fase 28 permitirá pausar el análisis y corregir manualmente cartas, stacks, acciones, apuestas, jugadores y board antes de continuar la sesión.
