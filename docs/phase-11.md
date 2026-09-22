# Fase 11 — Mesa y eventos en directo

`/live` reúne el vídeo y un panel lateral de **Mano actual**, con Hero, board, bote, stack de Hero, calle y turno observado. Debajo aparecen los eventos de la partida y el acceso a las manos guardadas. Las lecturas detalladas y la configuración quedan después de esta vista principal.

En móvil, el resumen pasa debajo del vídeo. El stack de Hero requiere elegir explícitamente su asiento; no se deduce de su posición en la imagen. La selección se conserva en el navegador, puede borrarse con «Sin asignar» y no modifica el estado del backend. Revisa esa asignación al cambiar de mesa o layout.

Los importes conservan la unidad observada; no se convierten fichas a BB ni se completan valores desconocidos. Los campos sin lectura muestran «Sin confirmar» y los valores retenidos con evidencia dudosa indican «Última lectura conservada». Una captura terminada muestra el último estado observado y la condición incompleta cuando corresponda.

## Transporte de estado

El navegador deja de sondear `GET /api/capture`. Se suscribe a `/ws/live`, recibe un snapshot inicial y nuevas versiones cuando cambia la captura: inicio, frame procesado y guardado, finalización, error o parada.

El JPEG de previsualización conserva su endpoint HTTP y su mecanismo de actualización de la fase 2. Las órdenes de iniciar/detener y la consulta del archivo también siguen siendo HTTP. El snapshot WebSocket no incluye imágenes binarias: transporta estado, metadata del frame, métricas, lecturas y la ventana de eventos. Vídeo y estado tienen entregas independientes; no se promete sincronización exacta entre el JPEG visible y un snapshot concreto.

Mensajes:

```json
{"type":"capture.subscribe"}
```

```json
{
  "version": 1,
  "type": "capture.snapshot",
  "connection_id": "identidad-de-esta-conexion",
  "sequence": 3,
  "timestamp": "2026-09-20T12:00:00+00:00",
  "payload": {
    "capture": {
      "server_id": "identidad-del-motor",
      "revision": 12,
      "capture_id": "identidad-de-captura",
      "state": "running"
    }
  }
}
```

El ejemplo omite los demás campos de `CaptureStatus` por brevedad. El servidor transmite el mismo contrato completo que la API, añadiendo `server_id` y `revision` a ambos transportes. Una segunda suscripción en el mismo socket es idempotente. Sin suscripción, se mantiene el protocolo previo de `system.ready`, `ping`, `system.pong` y errores.

Hay tres secuencias distintas:

- La del sobre WebSocket, independiente por conexión.
- La revisión de captura, creciente entre fuentes dentro de un motor. Su `server_id` cambia al reiniciar el backend.
- La secuencia de eventos de póker, relativa a `scope_id`, que mantiene el contrato y archivo de las fases anteriores.

El cliente descarta mensajes repetidos o atrasados de la conexión y snapshots con una revisión anterior. Las respuestas HTTP a órdenes tampoco pueden sustituir un estado más reciente. Al reconectar se acepta el snapshot del servidor actual, incluso si su revisión volvió a cero tras un reinicio. Los callbacks tardíos de otro socket no cierran la conexión nueva.

## Reconexión y límites

Si se interrumpe WebSocket, la interfaz conserva el estado y muestra que faltan actualizaciones. Se vuelve a suscribir al conectar. Reemplaza el snapshot completo y su ventana de eventos, sin añadir duplicados a una lista acumulada. El registro de conexión continúa limitado a 40 mensajes y no incorpora cada snapshot.

`CaptureHub` conserva un único snapshot reciente y cada suscriptor una cola de **un elemento**. Un cliente lento recibe la versión más reciente, con un máximo de cinco envíos de captura por segundo; puede omitir snapshots intermedios. El productor de vídeo y la persistencia no esperan a los sockets. Un envío que no termina en cinco segundos provoca el cierre de esa conexión. Al salir se cancelan sus tareas y se libera su suscripción, usando un [grupo de tareas de AnyIO](https://anyio.readthedocs.io/en/stable/tasks.html).

La ventana de eventos sigue limitada a 40. Tras una desconexión larga puede haber eventos anteriores fuera de la ventana; se consultan en el archivo de manos. El contador y la exportación existente indican la retención disponible. No hay replay ilimitado de mensajes WebSocket ni transporte entre varios workers. Se mantiene **un único worker** de backend.

El historial principal oculta por defecto las revisiones `GAME_STATE_UPDATED`; «Incluir cambios de estado» permite mostrarlas. Conserva cartas, límites y acciones, con jugador disponible, importe total de la calle y tiempo relativo de fuente `HH:MM:SS`. No se confunde ese tiempo con la hora de llegada del mensaje. No se calculan estrategias, equity ni recomendaciones en esta fase.

## Ejecutar y probar

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_ocr_video.py
```

1. Abre http://localhost:5173/live y reproduce `sample_data/ocr-demo.avi`.
2. Selecciona **Asiento 1** como Hero. Comprueba las cartas, el flop, el bote y el stack en el panel lateral.
3. Abre `/live` en otra pestaña: recibe la captura en curso sin reiniciarla.
4. Al terminar el vídeo, el último estado queda visible como incompleto. Las acciones de `actions-demo.avi` aparecen en el historial inferior.

Backend y navegador:

```powershell
docker compose build backend
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm zeros-backend-tests
```

Para incluir PostgreSQL, conserva la base exclusiva de pruebas de la fase 9:

```powershell
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`, con Compose en marcha y los seis vídeos de demo generados:

```powershell
npm run build
npm run format:check
npm test
```

Las pruebas nuevas verifican broadcast a dos suscriptores, estado inicial y reconexión, inicio/frame/parada, identidad tras reinicio, una cola limitada con mil publicaciones y desconexión de un socket bloqueado. El navegador bloquea las peticiones de sondeo HTTP de estado y exige cero peticiones; comprueba dos pestañas, interrupción y recuperación del socket, rechazo de un snapshot atrasado, ausencia de eventos duplicados y disposición móvil.

## Archivos y siguiente fase

Validación realizada: **233 pruebas del backend aprobadas** en Docker, con Tesseract real y PostgreSQL de pruebas; **15 pruebas del navegador aprobadas** contra Compose. Compilación TypeScript/Vite y comprobación Prettier correctas. Revisadas las capturas del vídeo y la mano actual en escritorio y móvil. Frontend, backend y base de datos quedaron saludables.

- Nuevo `backend/app/websocket_engine/capture_hub.py`; extensión del protocolo en `routes.py` e integración de publicaciones en CaptureEngine y arranque de la aplicación.
- `LiveProvider`, `protocol.ts` y `CaptureProvider`: suscripción, validación, revisión y reconexión.
- Nuevo `frontend/src/live/CurrentHand.tsx` y `styles/live.css`; reorganización de `/live`, eventos legibles y selector del asiento de Hero.
- Pruebas `backend/tests/test_live_capture.py` y `frontend/tests/live-scenario.ts`; documentación y versión 0.11.0.

Continúan los límites del reconocimiento sintético: falta calibración de salas reales y una sesión prolongada de ocho horas. La fase 12 añadirá el motor matemático a partir de GameState, separado de la lectura de vídeo.
