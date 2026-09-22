# Fase 8 — Event Engine

La aplicación dispone de un flujo de eventos estructurados y de un reproductor que reconstruye el `GameState` usando únicamente un checkpoint y esos eventos. El reconocimiento de vídeo emite hechos confirmados de cartas y estado. El contrato también admite límites de mano y acciones, preparados para los productores de las fases 9 y 10; todavía no se deducen de cambios OCR.

## Contrato de eventos

`PokerEvent` es un modelo validado e inmutable. Su contrato, incluido el estado resultante, aparece en `/docs` a través de la respuesta de `/api/events`.

| Campo | Significado |
| --- | --- |
| `schema_version` | Versión del contrato, actualmente 1 |
| `scope_id` + `sequence` | Identidad del evento: captura y número consecutivo desde 1 |
| `type` | Tipo de evento del catálogo |
| `frame_id`, `timestamp` | Frame confirmatorio y segundos de la fuente; no hora de servidor ni instante exacto de una acción |
| `hand_id` | Mano asociada o nulo cuando aún no se conoce |
| `player_id` | Referencia al asiento de esta captura, cuando corresponde |
| `amount`, `unit` | Apuesta total visible en la calle y su unidad para acciones con importe |
| `confidence` | Confianza disponible de la evidencia o nulo si no existe una puntuación agregada |
| `state_after` | `GameState` inmutable resultante, sin frames, OCR bruto ni estrategias |

Los importes son cadenas decimales exactas: `"450"`, no números de coma flotante. En una subida, `amount` significa **apuesta total resultante**, no la diferencia pagada; la fase de inferencia deberá aportar esa interpretación explícita. El importe/unidad coinciden con `current_bet`/`bet_unit` del jugador resultante. Fold y check no llevan importe. Las acciones requieren jugador, mano y confianza. All-in y fold requieren el correspondiente indicador confirmado en el estado.

El contrato valida referencias de captura/mano/jugador, seis asientos únicos, cartas válidas sin duplicados, calle compatible, importes no negativos, confianza entre 0 y 1 y tiempos finitos. Valida estructura y coherencia de datos; no pretende verificar todavía toda la legalidad de una partida.

Tipos disponibles:

- Hechos emitidos ahora: `GAME_STATE_UPDATED`, `HOLE_CARDS_DETECTED`, `FLOP_DEALT`, `TURN_DEALT`, `RIVER_DEALT`, `BOARD_CARDS_UPDATED`, `HERO_CARDS_CLEARED`, `BOARD_CARDS_CLEARED`.
- Contratos preparados y probados con entradas explícitas: `HAND_STARTED`, `HAND_FINISHED`, `PLAYER_FOLDED`, `PLAYER_CHECKED`, `PLAYER_CALLED`, `PLAYER_BET`, `PLAYER_RAISED`, `PLAYER_ALL_IN`.

Un cambio confirmado de valores produce primero `GAME_STATE_UPDATED`. Si ese frame confirma cartas, siguen sus eventos visuales, todos con el mismo estado resultante y secuencias distintas. El evento de estado no atribuye una causa de póker a los importes observados. Los frames repetidos no generan eventos; los cambios exclusivos de confianza tampoco. Una retransmisión idéntica del mismo tipo/jugador/frame se reconoce; una versión contradictoria se rechaza.

Los eventos de cartas heredan la confianza de las cartas confirmadas. Los vaciados y actualizaciones agregadas usan nulo porque no tienen una puntuación comparable. No se inventa un 100% de confianza. Los paneles previos de cartas y diferencias de estado se conservan por compatibilidad: son otras vistas de las observaciones, no otros eventos que deban concatenarse a este flujo.

## Retención, consulta y reproducción

El motor conserva los últimos **40 eventos**, un checkpoint y el último estado reproducido. Al expulsar un evento, el checkpoint avanza hasta su estado resultante. No se guardan imágenes en este historial ni crece una lista de eventos sin límite.

`GET /api/capture` añade `observation_state.event_stream` con `scope_id`, `event_count`, `first_sequence`, `dropped_events`, `capacity` y un resumen de los eventos sin snapshots. Así, el sondeo habitual del panel no transporta 40 estados completos.

`GET /api/events?scope_id=…&after=0` devuelve:

```text
schema_version, scope_id, requested_after, gap, last_sequence
checkpoint: sequence, frame_id, timestamp, state
events: eventos completos con state_after
```

`scope_id` es obligatorio. Si la captura cambió, se devuelve 409; un cursor negativo o posterior al último evento devuelve 422. Si el cursor quedó fuera del historial retenido, `gap=true` y se incluye el checkpoint disponible; **no se afirma que el historial esté completo**. Un cursor dentro del historial recibe el estado en ese punto y los eventos posteriores. Con el cursor más reciente se devuelve una lista vacía.

`EventReplay` consume únicamente checkpoint y eventos validados. Rechaza huecos, desorden, retrocesos temporales, capturas mezcladas y retransmisiones contradictorias. Repetir exactamente el último evento es idempotente. `replay_batch` comprueba también que no falte la cola declarada en `last_sequence`. Una reproducción de un prefijo no conoce cambios posteriores. Los snapshots quedan congelados y no pueden modificarse al llegar nuevos frames.

Cada evento lleva el estado completo resultante para que la reproducción sea sencilla y verificable. Es una elección funcional inicial; no se ha implementado compresión de diferencias, almacenamiento duradero ni reconstrucción de lecturas OCR originales. Se reconstruyen los valores del `GameState`; la evidencia de cada campo sigue en la API de estado y no se recrea a partir del historial.

## Interfaz y ejecución

En `/live` aparece **Eventos de la partida**, con tipo, secuencia, tiempo, frame y confianza. El panel señala capturas terminadas, desconexión y pérdida de eventos antiguos. **Exportar historial disponible (JSON)** descarga el checkpoint y los eventos completos. No ofrece recomendaciones en ninguno de los dos modos.

```powershell
docker compose up --build -d --wait
```

Reproduce `sample_data/cards-demo.avi` para ver Hero, flop, turn, river y vaciados, o `sample_data/ocr-demo.avi` para ver cambios de importes. Los generadores existentes siguen disponibles si necesitas crear estos archivos:

```powershell
backend/.venv/Scripts/python backend/scripts/create_card_video.py
backend/.venv/Scripts/python backend/scripts/create_ocr_video.py
```

Después de exportar el JSON, reconstruye su estado sin servidor ni vídeo:

```powershell
backend/.venv/Scripts/python backend/scripts/replay_events.py C:\ruta\zeros-events.json
```

El resultado contiene `sequence`, `history_truncated`, `checkpoint_sequence` y `state`. Si el historial está recortado, puedes reproducir el tramo disponible, pero no recuperar acciones ya descartadas. Tampoco se conserva el historial al reiniciar el backend o empezar otra captura.

## Archivos y comprobaciones

- Nuevo `backend/app/event_engine/`: contratos, validación del estado, motor, puente desde observaciones, reproductor y ruta de consulta.
- Nuevo `backend/scripts/replay_events.py` y `backend/tests/test_events.py`.
- Integración en `game_state_engine/engine.py`, exportación diferida de su clase para evitar dependencia circular, registro de rutas y versión 0.8/fase 8.
- Nuevo `frontend/src/events/` y estilos; Live, contratos, portada y progreso actualizados.
- Pruebas de vídeo de cartas y escenarios de navegador ampliados para validar secuencias, reproducción, exportación, reinicio y vistas de escritorio/móvil.
- El contenedor de pruebas incluye los scripts para comprobar el reproductor independiente. No se añaden dependencias Python o npm ni se cambia `app.md`.

La revisión de la fase anterior encontró Docker detenido y después fallos de las pruebas de cartas bajo carga simultánea. La secuencia corta del backend exponía cada calle un segundo, insuficiente en esta máquina para garantizar las tres lecturas procesadas que exige el filtro. Se amplió a tres segundos por calle y 5 FPS, manteniendo las aserciones de calles y ausencia de duplicados. Las suites con capturas se verifican separadamente para no competir por CPU. El pipeline sigue descartando frames antiguos cuando corresponde; no se relajan los umbrales de reconocimiento.

Comprobaciones:

```powershell
docker compose build backend
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm zeros-backend-tests
```

Después, desde `frontend/`, con los cuatro vídeos generados y sin captura activa:

```powershell
npm run build
npm run format:check
npm test
```

Las pruebas del nuevo módulo cubren reproducción sin visión, contrato de acciones, orden/duplicados, aislamiento temporal, snapshots inmutables, estados corruptos, truncado, cursores, API, reinicio y CLI. Las pruebas de integración reproducen los eventos exportados por el pipeline real en ambos modos.

Resultado final de validación:

- **188 pruebas de backend verificadas con Tesseract real en Docker**: 187 pasaron en la ejecución completa; una prueba de vídeo no confirmó el turn a tiempo y pasó al repetirla aisladamente. Sigue existiendo sensibilidad de esta prueba a la carga y al descarte temporal de frames; no se rebajaron sus aserciones. Permanecen los dos avisos de deprecación previos de Starlette/AnyIO.
- **33 pruebas nuevas de eventos aprobadas**, incluida la CLI, validación estructural y reproducción de contratos de acciones sin visión.
- **12 pruebas de navegador aprobadas en una ejecución completa**, con descarga JSON, secuencias de cartas, OCR, reinicio, navegación, editor de layout y captura nativa de pestaña.
- Compilación TypeScript/Vite y formato correctos. Panel de eventos revisado en escritorio y móvil, sin desbordamiento horizontal.
- Los tres servicios de Compose están saludables y no se observaron errores del pipeline ni respuestas 500 en los logs revisados.

## Límites y siguiente fase

Los valores todavía pueden proceder de regiones confirmadas en momentos distintos. No hay detección automática de acciones ni manos completas a partir del vídeo, identidad persistente de rivales, persistencia en PostgreSQL ni estrategia. El historial es acotado y volátil. El flujo llega a la UI mediante el sondeo HTTP existente; la entrega por WebSocket corresponde a una fase posterior.

La fase 9 detectará inicio y final de manos combinando señales de la mesa y usará `HAND_STARTED`/`HAND_FINISHED`. La fase 10 inferirá acciones con múltiples señales y utilizará los contratos `PLAYER_*`.
