# Fase 28 — Corrección manual

## Revisión de la fase anterior y resultado

Se revisaron el buffer temporal de la fase 27, el procesamiento en dos workers y las instantáneas inmutables. En `/live` se incorpora **Corrección manual**: pausar el análisis, editar la lectura del frame actual, guardar la corrección y reanudar dentro de la misma captura y mano. Se admiten cartas de Hero, board, nombre del jugador, stack, apuesta total de la calle y etiqueta de acción de los seis asientos.

El servidor valida cartas y duplicados entre Hero y board, cantidades de cartas, seis asientos sin repetir, importes decimales no negativos de hasta dos decimales, unidades y etiquetas. Vaciar un campo conocido retira su valor. Las unidades se eligen por separado para stack y apuesta: fichas sin símbolo, `$`, `€`, `£` o `BB`. Los IDs de asiento y la identidad de la mano no se editan; «Jugador» corrige el nombre observado.

## Pausa y reanudación

La pausa espera a que finalice cualquier llamada nativa de visión y su publicación antes de admitir ediciones. No se cancela un OCR a mitad de trabajo ni se libera su imagen mientras se utiliza. Productor y consumidor quedan detenidos y la cola sigue limitada; puede conservar un frame ya reservado para procesarlo al reanudar. La parada y el cierre despiertan también a los workers pausados.

Para archivos se congela el reloj de reproducción: el tiempo empleado corrigiendo no se suma al tiempo del vídeo. En pantalla, el navegador continúa enviando imágenes y el adaptador conserva solo la más reciente; el mundo real no se pausa. El buffer tampoco continúa ampliándose mientras el productor está pausado. Al reanudar una pantalla puede haber acciones no observadas durante ese intervalo; no se reconstruyen por suposición.

`state` sigue siendo `running` mientras la captura está abierta y pausada; `analysis_control.paused` distingue ese estado. `analysis_control.revision` cambia al pausar, corregir y reanudar; `last_correction_id` identifica la última corrección guardada en esa captura. Capturas nuevas reinician el control. Solo se corrige el último frame analizado de una captura en ejecución y pausada, nunca un frame histórico elegido en el buffer.

## Aplicación de etiquetas y conservación del historial

Se prepara una copia del GameState y sus filtros, se valida el resultado completo y se guardan dataset, imagen, evento y estado de mano en una sola transacción. Solo después del commit se sustituye el estado en memoria. Si falla el almacenamiento, la respuesta es 503, el estado no cambia y el análisis permanece pausado para reintentar.

Las cartas y textos corregidos se introducen en los filtros temporales para que el siguiente frame no restaure inmediatamente un valor antiguo retenido. La evidencia del GameState identifica esas etiquetas con `source: "manual"`; el panel de estado las presenta como **Corrección manual**. Las observaciones posteriores pueden sustituirlas con la confirmación visual habitual. No son bloqueos permanentes de valores ni una modificación de la imagen original.

La etiqueta manual de acción actualiza `observed_action`, turno y las marcas de fold/all-in correspondientes; no crea un evento `PLAYER_*` inferido ni afirma haber comprobado la legalidad de esa acción. Se borra la acción pendiente del detector y se conserva su contador acumulado. Las correcciones emiten `MANUAL_CORRECTION` con ID propio; reanudar emite `ANALYSIS_RESUMED`. Ambos participan en el replay ordenado.

El historial contextual de rivales/preflop afectado se invalida y requiere reconfirmación después de reanudar. Un marcador manual o de reanudación impide atribuir una acción futura a una decisión anterior no resuelta. Tampoco se vuelve a congelar la decisión del mismo turno corregido/interrumpido hasta que haya otra acción confirmada o cambie el contexto de mano/calle. Las decisiones y estrategias ya archivadas conservan sus entradas originales: no se reescriben con etiquetas conocidas después.

Mientras está pausado se ocultan/inhiben los nuevos resultados de estrategia y matemáticas del estado actual. Un cálculo ya iniciado sobre una instantánea antigua puede terminar y archivarse con esa instantánea, sin convertirse en resultado del estado corregido. Los permisos de `LIVE_REAL_MONEY` y la liberación de revisión mantienen su comportamiento.

## Dataset persistente

La tabla `manual_corrections` se crea automáticamente en SQLite y PostgreSQL. Cada fila es una etiqueta append-only con ID UUID y revisión únicos, captura/scope/mano/modo, fecha UTC, motivo y petición, ID/timestamp del frame, observación original sin modificar, GameState anterior y posterior y secuencia de evento. El JPEG se guarda aparte en la misma fila, codificado en base64; los listados no lo incluyen.

Se prefiere el JPEG a resolución original del buffer. Si ya no está disponible se utiliza el preview del mismo frame, limitado a 1280 × 720. El registro distingue las dimensiones de la imagen guardada de las de la observación original, permitiendo escalar coordenadas al preparar un dataset. Las imágenes son JPEG con pérdida. Una etiqueta guardada no demuestra por sí sola que el valor humano sea correcto; no se entrena ni evalúa un modelo automáticamente.

Las etiquetas sobreviven a cambios de captura y reinicios. La exportación es paginada y está separada por modo. Puede abrirse el JSON de la captura desde el panel; la imagen se descarga con su endpoint. No se incluyen resultados de estrategia ni claves del explicador.

## API

| Método y ruta | Uso |
| --- | --- |
| `POST /api/capture/{capture_id}/analysis/pause` | Congelar análisis; devuelve el estado actual. |
| `POST /api/capture/{capture_id}/analysis/resume` | Reanudar la misma captura. |
| `POST /api/capture/{capture_id}/corrections` | Guardar un parche sobre el frame pausado. |
| `GET /api/capture/{capture_id}/corrections?after=0&limit=20` | Exportar etiquetas sin imágenes; `next_after` permite continuar. Máximo 100 por página. |
| `GET /api/capture/{capture_id}/corrections/{id}/frame` | Recuperar la imagen asociada a una etiqueta de ese modo y captura. |

Ejemplo de corrección; usar el frame y revisión devueltos después de pausar:

```json
{
  "id": "a5d206ac-8d6c-4466-b24c-e729afcc19ca",
  "expected_frame_id": 42,
  "expected_revision": 1,
  "reason": "El OCR confundió el stack de Hero",
  "hero_cards": ["As", "Kd"],
  "players": [{"seat": 1, "stack": {"value": "100.25", "unit": "BB"}}]
}
```

Los campos omitidos se conservan. Para vaciar cartas usar `[]`; para retirar nombre, stack o apuesta usar `null`. `players[].action` admite `NONE`, `ACTIVE`, `FOLD`, `CHECK`, `CALL`, `BET`, `RAISE` y `ALL-IN`. Se rechazan campos desconocidos y parches vacíos. Una petición repetida con el mismo UUID y contenido es idempotente mientras siga pausada la captura; reutilizarlo con otro contenido, o usar un frame/revisión antiguos, devuelve 409. La interfaz conserva el UUID al reintentar el mismo contenido. Los listados e imágenes llevan `Cache-Control: no-store`.

## Archivos principales

- `backend/app/game_state_engine/corrections.py`, `correction_store.py`: contratos, aplicación sobre copia y dataset SQL.
- `backend/app/capture_engine/engine.py`, `routes.py`, `file_source.py`: control de pausa, commit y reloj de archivo.
- `backend/app/pipeline_engine/pipeline.py`: sincronización de productor y consumidor.
- `backend/app/game_state_engine/models.py`, `action_engine/engine.py`, `event_engine/{models,engine}.py`: evidencia manual, etiquetas y eventos.
- `backend/app/hand_reconstructor/store.py`, `decision_engine/{tracker,evaluation}.py`, `opponent_model/engine.py`, `strategy_engine/service.py`: persistencia e invalidación del contexto afectado.
- `frontend/src/capture/ManualCorrection.tsx`, `styles/corrections.css`, tipos de captura/juego, Live, GameStatePanel y etiquetas de eventos: formulario, estado visible y exportación.
- `backend/tests/test_manual_corrections.py`, `frontend/tests/corrections.spec.ts`: pruebas nuevas; marcadores de versión 0.28, README y este documento.

## Cómo ejecutar y comprobar

Arrancar con `docker compose up --build -d --wait` y abrir `http://localhost:5173/live`. Iniciar un vídeo o pantalla, desplegar **Corrección manual**, pulsar **Pausar análisis**, editar los campos necesarios y el motivo, y pulsar **Guardar corrección**. Comprobar el valor y su procedencia manual en el estado de partida, abrir el dataset y pulsar **Reanudar análisis**. La captura conserva su ID.

Desde la raíz, ejecutar `python -m pytest backend/tests/test_manual_corrections.py -q`. El caso de PostgreSQL necesita una base exclusiva configurada en `HAND_TEST_POSTGRES`. La regresión completa se ejecuta en Docker con Tesseract, SQLite y esa base de PostgreSQL; nunca se introducen datos sintéticos en la base principal.

Para repetir el navegador, usar los contenedores aislados con `scripts/seed_timeline_review.py --serve` y su frontend en 5174. Definir `E2E_BASE_URL=http://127.0.0.1:5174`, `E2E_BROWSER_CHANNEL=msedge`, `LATENCY_E2E=1` y `TIMELINE_E2E=1`. Desde `frontend`:

```powershell
node node_modules/@playwright/test/cli.js test tests/app.spec.ts tests/latency.spec.ts tests/timeline.spec.ts tests/sampling.spec.ts tests/history.spec.ts tests/corrections.spec.ts --workers=1
node node_modules/@playwright/test/cli.js test -c playwright.training.config.ts training-tests/strategy.spec.ts --workers=1
npm.cmd run build
npm.cmd run format:check
```

Las pruebas cubren edición completa, validación y ausencia de mutaciones parciales, etiquetas antes/después, origen y dimensiones del JPEG, PostgreSQL, reintentos, revisiones antiguas, espera de un worker nativo, parada mientras está pausado, reloj de archivo, reanudación en el mismo scope y separación entre capturas. También verifican que una corrección no reescriba ni reabra una decisión congelada y que la evaluación no salte una corrección para atribuir una acción posterior.

Resultado: **621 pruebas de backend correctas**, incluidas las de PostgreSQL, **12 escenarios de navegador correctos** y **1 escenario de entrenamiento correcto**. Compilación TypeScript/Vite, formato y `git diff --check` correctos. La prueba del formulario se ajustó para localizar el selector de acción por su rol y nombre accesible; la ejecución posterior de los doce escenarios pasó. Se revisó el formulario en escritorio y móvil y se ajustaron el tamaño y contraste de los campos. Quedan dos avisos de deprecación de las dependencias de TestClient. Los otros casos de `tests/capture.spec.ts`, que requieren vídeos adicionales, no forman parte de esta selección de navegador.

La versión 0.28 quedó levantada con los tres servicios saludables, `LIVE_REAL_MONEY` y PostgreSQL en la instancia principal. Las etiquetas y manos sintéticas de las pruebas se generaron en contenedores y bases aislados; los contenedores auxiliares se detuvieron al terminar.

## Limitaciones y siguiente fase

Solo se corrige el frame actual mientras está pausado; no hay edición retroactiva del buffer ni reconstrucción automática de un tramo perdido. El nombre del jugador se edita dentro del mismo asiento, sin mover identidades entre asientos. No se editan pot, ciegas ni botón en este formulario. Las etiquetas manuales de acciones son descriptivas y no sustituyen una historia legal de apuestas validada.

Los valores pueden volver a cambiar al llegar evidencia visual nueva. El dataset es persistente y crece con las correcciones explícitas; la exportación está paginada, pero esta fase no añade borrado ni entrenamiento automático. Una pausa prolongada de pantalla puede perder acciones reales. La reconfirmación del contexto estratégico no recupera esas acciones ausentes.

La fase 29 verificará la estabilidad y los límites de memoria durante sesiones de 2, 4 y 8 horas.
