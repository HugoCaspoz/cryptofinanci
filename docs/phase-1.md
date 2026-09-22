# Fase 1 — Base del proyecto

## Construido

- React, TypeScript y Vite; navegación por `/`, `/live`, `/sessions` y `/session/:id`, más página de dirección desconocida.
- FastAPI con `/health`, colección vacía de sesiones, detalle inexistente (404) y `/ws/live`.
- WebSocket compartido entre páginas, handshake validado, ping cada 5 segundos, medición de ida y vuelta y reconexión con esperas de 1, 2, 4, 8 y hasta 10 segundos. Tras 15 segundos sin mensajes válidos se reinicia la conexión.
- Registro de hasta 40 mensajes en memoria. Cierre de conexiones y temporizadores al desmontar el proveedor.
- Estados diferenciados de carga, vacío, error y sesión inexistente.
- Diseño adaptable a escritorio y móvil, navegación por teclado e indicadores de conexión textuales.
- Docker Compose para frontend, backend y PostgreSQL. El frontend sirve las rutas de React y reenvía HTTP/WebSocket al backend.

## Archivos

Se añaden `backend/`, `frontend/`, `compose.yaml`, `.env.example`, `.gitignore`, `README.md` y este documento. `app.md` se conserva intacto. Los detalles de arranque y pruebas están en el README.

## Contrato WebSocket v1

El servidor emite primero:

```json
{
  "version": 1,
  "type": "system.ready",
  "connection_id": "uuid",
  "sequence": 1,
  "timestamp": "2026-09-17T12:00:00+00:00",
  "payload": {
    "mode": "LIVE_REAL_MONEY",
    "phase": 1,
    "capture_available": false,
    "strategy_available": false
  }
}
```

El cliente envía `{"type":"ping"}`; el servidor responde `system.pong` con el mismo sobre y payload vacío. `sequence` aumenta dentro de cada conexión, no es un identificador global de sesión. Las fechas son UTC. La latencia usa un reloj monotónico en el navegador y mide el trayecto completo por el proxy.

El servidor responde `system.error` con `INVALID_JSON` o `UNSUPPORTED_MESSAGE` ante entradas inválidas y sigue atendiendo. Un mensaje de texto mayor de 4096 caracteres cierra la conexión con código 1009; el arranque documentado de Uvicorn limita además el transporte a 4096 bytes.

Estos mensajes son de infraestructura. El contrato de eventos de poker, la persistencia, el replay y las decisiones inmutables corresponden a fases posteriores.

## Comprobaciones

- API: salud, sesiones vacías y 404 para identificadores inexistentes.
- WebSocket: ambos modos, orden de mensajes, ping/pong, mensajes malformados, rechazo de cambios de modo, exceso de tamaño y reconexión.
- Navegador: conexión con el backend real, navegación, enlaces directos, recarga, recuperación de errores HTTP, reconexión y ausencia de desbordamiento horizontal en móvil.
- Compilación de TypeScript y bundle de producción.
- Configuración, construcción y arranque de Compose cuando Docker esté disponible.

Validación realizada el 17 de septiembre de 2026: 8 pruebas de backend y 5 pruebas de navegador superadas; compilación de producción correcta; los tres servicios de Compose arrancados y saludables. Las pruebas de navegador se ejecutaron contra el frontend de producción servido por Nginx y el backend real. Las dependencias de pruebas emiten avisos de deprecación de Starlette/AnyIO; no impiden la ejecución.

## Límites y fase siguiente

No hay sesiones persistidas, captura ni motor de poker. PostgreSQL está provisionado pero todavía no está integrado con la API. No se generan recomendaciones en ningún modo. La separación de la información estratégica y su desbloqueo deberán verificarse cuando se incorpore ese motor.

La fase 2 conectará vídeo de archivo y captura de pantalla/ventana. Se revisará primero esta base y se mantendrá el procesamiento como flujo, sin esperar a leer un vídeo completo.

## Referencias de implementación

- [Vite: inicio y requisitos](https://vite.dev/guide/).
- [FastAPI: WebSockets](https://fastapi.tiangolo.com/advanced/websockets/).
- [React Router: instalación declarativa](https://reactrouter.com/start/declarative/installation).
