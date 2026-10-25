# Fase 29 — Sesiones largas

## Revisión y cambios

Se revisaron los filtros, la cola, el buffer temporal, las decisiones, los perfiles, el WebSocket y las consultas del archivo. Se conserva el historial duradero en SQL y una ventana acotada de trabajo en memoria. No se guarda un vídeo completo de la sesión.

Se corrigieron dos casos concretos: las claves de deduplicación de muchas correcciones sobre un mismo frame podían sobrevivir a los eventos expulsados; y más de 128 cambios de identidad de jugadores detenían la captura. Ahora las claves caducan con el registro de 40 eventos y los perfiles inactivos antiguos salen de la caché sin detener la sesión. Sus estadísticas se conservan por identidad en SQL. Los IDs usan un contador creciente, sin reutilizar los de perfiles expulsados. Se mantienen fijados los perfiles necesarios para los últimos 20 showdowns pendientes.

Las claves de decisión tienen un límite explícito de 512 por mano. Si se alcanza, el motor se abstiene de crear más decisiones en esa mano, conservando las claves existentes para no duplicar turnos. La cola de persistencia de decisiones admite una pendiente, sin descartar la anterior. Una captura nueva sigue exigiendo guardar lo pendiente primero.

Las migraciones de manos activas y sesiones antiguas, la comprobación de fin de mano y la búsqueda de estrategia de una decisión consultan SQL en páginas de 100 filas. Así no se cargan todos los payloads de un archivo grande para esas operaciones. La migración sigue rechazando sesiones con modos mezclados y nunca libera automáticamente una revisión histórica.

## Qué se conserva

| Dato | Memoria durante la captura | Persistencia |
| --- | --- | --- |
| Frames normales | Buffer de 10–30 s, máximo 450 JPEG y 64 MiB; cola de procesamiento de 1–8 frames, 2 por defecto | No se archivan todos. |
| Eventos | Últimos 40 y un checkpoint; hasta 40 claves de deduplicación | `observed_events`, con estado por evento. |
| Cambios de estado / manos recientes | 40 cambios y 20 límites recientes | `observed_hands` y eventos de límites. |
| Decisiones | Una actual, 20 resúmenes recientes, hasta 512 acciones y 512 claves por mano; una escritura pendiente | Instantáneas inmutables, imagen de decisión, estrategia y evaluación existentes. |
| Perfiles | Hasta 128, incluidos activos y fijados por showdowns pendientes | Último snapshot y archivo `opponent_profiles` por identidad. |
| Imágenes importantes | Hasta 3 escrituras pendientes; normalmente se guardan de inmediato | Inicio/fin de mano y excepciones del procesamiento/publicación. |
| Correcciones | Estado actual corregido; sin una lista acumulativa en memoria | Dataset e imágenes de la fase 28. |
| Telemetría | 128 latencias por etapa, 512 muestras máximas de tasa, 128 orígenes | Informes de diagnóstico, a petición. |
| WebSocket | Un snapshot pendiente por suscriptor; la desconexión libera su cola | No se archivan los snapshots de transporte. |

Los límites de cola y buffer acotan las imágenes retenidas, no toda la memoria del proceso: existen arrays temporales, plantillas, cachés acotadas y trabajos nativos en curso. El número de conexiones simultáneas también influye en el consumo.

## Archivo selectivo de imágenes

`important_frames` guarda JPEG y metadatos de `hand_started`, `hand_finished` y `processing_error`. Los límites de mano incluyen `hand_id` y secuencia del evento. Un error registra etapa y clase de excepción, sin guardar el traceback como etiqueta. Se utiliza la imagen del frame que falló; si ya salió del buffer, se codifica el array que aún tiene el worker. No se sustituye por un frame posterior.

Los límites de mano usan el preview limitado a 1280 × 720; el frame de error puede conservar la resolución original. Las imágenes siguen siendo JPEG con pérdida. La espera de confirmación de una carta, una lectura desconocida o la falta de calibración no se consideran por sí solas errores para archivar: eso evitaría guardar casi todos los frames de una mesa no configurada. Un fallo de captura previo a obtener una imagen tampoco inventa una imagen del error.

Las escrituras son idempotentes por captura, frame y tipo. Si falla el almacenamiento se conserva una cola de hasta tres imágenes y la captura se detiene; antes de iniciar otra se reintenta lo pendiente. El error del archivo aparece en el estado y en depuración. Esta protección no garantiza conservar una imagen si el propio codificador falla ni recuperar datos pendientes después de perder el proceso sin almacenamiento disponible.

API paginada, separada por modo, sin análisis estratégico:

- `GET /api/capture/{capture_id}/important-frames?offset=0&limit=20`: metadatos, `has_more` y `next_offset`; máximo 100 por página.
- `GET /api/capture/{capture_id}/important-frames/{id}`: JPEG exacto; 404 para otra captura o modo.
- Ambas respuestas correctas incluyen `Cache-Control: no-store`.

El archivo de perfiles tiene acceso paginado mediante `HandStore.list_opponent_profiles(scope_id, mode, limit, offset)`. El estado en directo sigue mostrando solo su caché acotada; el dashboard histórico se abordará en la fase 30.

## Monitorización y registros

`/api/capture` y el WebSocket incluyen `session_health`: RSS actual del proceso, tiempo de fuente, cantidades retenidas, sus límites, imágenes importantes guardadas y posibles fallos del archivo. Son contadores de diagnóstico, no nuevos datos estratégicos. El RSS se toma cada cinco segundos de `/proc/self/statm` en Linux; en sistemas sin esa fuente se devuelve `null`. No representa solo el heap Python ni el consumo total de todos los contenedores.

En `/live`, **Depuración del pipeline** muestra RSS, horas de fuente, imágenes importantes y perfiles en memoria. Compose configura rotación `json-file` de 10 MB y tres archivos por servicio para los logs del backend, frontend y PostgreSQL. Los volúmenes SQL no se borran al recrear los contenedores.

## Validación medida

Informes conservados:

- [Sesión sintética acelerada](validation/phase29-soak.json).
- [Pipeline con reloj real](validation/phase29-pipeline.json).

La prueba acelerada recorrió **8 horas de tiempo de fuente**, con hitos de 2 y 4 horas, en **310,88 segundos reales**. Inspeccionó **288.001 frames** a una cadencia virtual de 10 FPS, pasando por el buffer, muestreo, cola, GameState, eventos, decisiones, perfiles, SQLite y un suscriptor lento. Las imágenes son sintéticas de 96 × 54 y las observaciones están etiquetadas: esta prueba no ejecuta OCR ni solver de EV.

| Hito de fuente | Heap Python retenido | RSS del proceso | JPEG retenidos | Perfiles en memoria |
| --- | ---: | ---: | ---: | ---: |
| 1 h, calentamiento | 790.786 B | 78.540.800 B | 301 | 128 |
| 2 h | 801.238 B | 79.855.616 B | 301 | 128 |
| 4 h | 811.393 B | 80.044.032 B | 301 | 128 |
| 8 h | 823.711 B | 80.121.856 B | 301 | 128 |

Entre 1 y 8 horas, el crecimiento medido del heap fue **32.925 bytes** y el del RSS, **1.581.056 bytes**. La ventana JPEG se mantuvo en 217.443 bytes. Al hito de 8 h había 24.974 eventos, 1.440 manos, 2.880 decisiones, 2.888 imágenes importantes, 8 correcciones y 2.887 perfiles archivados. Las correcciones y los errores horarios del generador son etiquetas sintéticas explícitas; no son fallos de una mesa real. El tamaño de SQL aumenta con el historial, mientras sus listas de trabajo quedan acotadas.

Se ejecutó además una fuente sintética de 640 × 360 durante **60 segundos de fuente con reloj real**, usando el CaptureEngine, sus workers y la codificación JPEG reales. La observación terminó a los 70,11 s de seguimiento, incluido el intervalo de muestreo final. Procesó 151 frames; retuvo 298 JPEG, unos 1,22 MiB, dentro de la ventana de 30 s. El informe confirma la liberación de los threads de captura y procesamiento al cerrar. Tampoco es un ensayo de OCR, vídeo externo o heap del navegador.

La regresión completa del backend, con Tesseract y PostgreSQL aislado, terminó con **631 pruebas correctas** y dos avisos de deprecación de las dependencias de TestClient. Incluye las pruebas de miles de ediciones, cambios de identidad y perfiles fijados, archivo histórico, lecturas SQL paginadas, imágenes de errores, límites de mano, reintentos e idempotencia del archivo. No se introdujeron datos sintéticos en la base principal.

Pasaron también **12 escenarios de navegador y 1 escenario de entrenamiento**, incluidos los contadores de retención y la imagen de inicio de mano. Compilación TypeScript/Vite, Prettier y `git diff --check`, correctos. Se verificó además que una escritura de perfil con revisión antigua no pueda revertir el archivo de perfiles, tanto en SQLite como en PostgreSQL. Los otros casos de `tests/capture.spec.ts`, que necesitan vídeos adicionales, no están incluidos en esta selección.

La instancia principal quedó saludable en versión 0.29, modo `LIVE_REAL_MONEY`, PostgreSQL y captura inactiva. Se detuvieron los contenedores auxiliares al terminar, conservando los informes y la base sintética de la ejecución completada en la carpeta de resultados.

## Cómo ejecutar y repetir

Arrancar con `docker compose up --build -d --wait` y abrir `http://localhost:5173/live`. Las ventanas y límites anteriores se aplican automáticamente; `FRAME_BUFFER_SECONDS` mantiene la configuración de la fase 27.

Desde la raíz, pruebas específicas:

```powershell
python -m pytest backend/tests/test_long_sessions.py -q
```

Para incluir los casos PostgreSQL, usar una base exclusiva mediante `HAND_TEST_POSTGRES`. La regresión completa en Docker monta `backend/app`, `backend/tests` y `backend/scripts` sobre la imagen de pruebas existente, pues los casos del archivo selectivo utilizan el generador sintético.

Con dependencias instaladas, el diagnóstico se puede repetir desde la raíz:

```powershell
python backend/scripts/soak_session.py --hours 8 --output-dir sample_data/soak-phase29
python backend/scripts/soak_session.py --pipeline-seconds 60 --output-dir sample_data/soak-phase29
```

`--hours` admite 2, 4 u 8. `--realtime` hace avanzar ese ensayo sintético al ritmo del reloj real y tarda las horas solicitadas; no se ejecutó en esta entrega. `--pipeline-seconds` admite de 1 a 600 segundos. El runner crea una SQLite temporal propia dentro del sistema que lo ejecuta, sin aceptar una ruta a la base principal, y copia su archivo al directorio de resultados al terminar. Cada ejecución genera un nombre nuevo; los informes JSON usan nombres estables. Las bases de diagnóstico no se versionan y ocupan disco hasta retirarlas.

En Docker, montar `backend/app` y `backend/scripts` en la imagen de pruebas y solo la carpeta de informes en `/reports`, ejecutando `python scripts/soak_session.py --hours 8 --output-dir /reports`. En la ejecución medida se utilizó SQLite temporal dentro del contenedor para separar la prueba de memoria de la latencia de un bind mount de Windows.

El navegador se verifica con los contenedores aislados de las fases anteriores, `E2E_BASE_URL=http://127.0.0.1:5174`, `E2E_BROWSER_CHANNEL=msedge`, `LATENCY_E2E=1` y `TIMELINE_E2E=1`: ejecutar los seis archivos `app`, `latency`, `timeline`, `sampling`, `history` y `corrections` con `--workers=1`, y después `training-tests/strategy.spec.ts` con `playwright.training.config.ts`. La prueba de latencias comprueba los límites de `session_health`; la de entrenamiento verifica que el inicio de mano tenga imagen archivada.

## Archivos principales y límites actuales

Cambios en `event_engine/engine.py`, `decision_engine/{tracker,service}.py`, `opponent_model/engine.py`, `hand_reconstructor/store.py` y `feedback/store.py`; nuevos `capture_engine/important_frames.py`, `pipeline_engine/memory.py`, `scripts/soak_session.py` y `tests/test_long_sessions.py`; integración en el pipeline, motor y rutas de captura, tipos y depuración del frontend, Compose, versiones y documentación.

Las pruebas muestran retención acotada en los escenarios ejecutados; **no certifican ocho horas reales continuas con OCR, una mesa externa, todos los modelos de estrategia y un navegador abierto**. Cambios de resolución, plantillas reales, carga del equipo, disco lleno y conexiones simultáneas requieren su propio ensayo. La caché de perfiles fija ciertos datos de showdowns pendientes dentro de su límite; confirmar contextos sigue siendo necesario para estadísticas fiables. Al alcanzar el límite de decisiones de una mano se abstiene del análisis adicional.

El almacenamiento duradero crece con eventos, decisiones, límites de mano, imágenes seleccionadas y correcciones. No hay una política de borrado o cuota para SQL en esta fase. Las mediciones de memoria pertenecen a este equipo y no son un presupuesto garantizado de RAM para cualquier entrada.

La fase 30 reunirá las métricas de sesión, errores más costosos y revisión de decisiones en el dashboard final.
