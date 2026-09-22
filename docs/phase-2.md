# Fase 2 — Fuente de vídeo en directo

## Construido

- Interfaz `VideoSource` con `start()`, `stop()` y `get_frame()`.
- `FileVideoSource`, mediante OpenCV y su backend FFmpeg, reproduce archivos según un reloj monotónico. Extrae los frames correspondientes al tiempo transcurrido en lugar de leer y procesar todo el vídeo por adelantado.
- `ScreenCaptureSource` recibe imágenes de la pantalla, ventana o pestaña que el usuario elige con `getDisplayMedia`. Esta separación permite capturar el escritorio del host y mantener el backend en Docker.
- `CaptureEngine` controla una fuente por instancia, con estados `idle`, `running`, `ended`, `stopped` y `error`.
- Cada `Frame` incluye `frame_id`, `timestamp`, `image` BGR y `fps`. El identificador aumenta dentro de cada captura; se combina con un `capture_id` UUID para distinguir reinicios.
- API de inicio, parada, estado y previsualización JPEG. La fuente se libera al parar, terminar, fallar o cerrar la aplicación.
- Controles en `/live`, selección de FPS, progreso de fuente, preview desde el backend, mensajes de error y estado de fin de vídeo. La captura de pantalla se mantiene al navegar por las rutas de React.
- Generador de vídeo de prueba con reloj visible. La muestra no contiene cartas ni simula reconocimiento de poker.

## Decisiones técnicas

El permiso para compartir lo gestiona el navegador mediante un gesto explícito del usuario. El producto no selecciona ni comparte automáticamente una superficie. La imagen local pasa por un canvas, se envía en JPEG al adaptador del backend y vuelve como preview. El frontend no muestra un vídeo local haciéndolo pasar por resultado del servidor.

El timestamp de archivo representa tiempo de fuente, calculado a partir del índice del frame y sus FPS originales. Para pantalla representa segundos desde el inicio hasta la recepción en el backend: todavía no se sincronizan relojes del navegador y servidor. Es una limitación explícita para el posterior diseño de observaciones y snapshots.

La captura se ejecuta en una tarea de ciclo de vida controlado; la lectura y codificación de OpenCV se delegan a un thread para mantener disponible la API. La parada espera que termine una lectura en curso antes de cerrar el decodificador. No se implementa aún el pipeline de análisis con colas de la fase 3.

El backend mantiene el último JPEG de preview y el adaptador de pantalla conserva como máximo un frame pendiente. El frontend envía como máximo un frame a la vez y libera las URL de imágenes anteriores. No se acumula un historial de imágenes en memoria.

La salud y el handshake WebSocket anuncian fase 2 y `capture_available: true`. `strategy_available` sigue siendo `false` para ambos modos. El canal `/ws/live` conserva sus mensajes de infraestructura; la preview usa HTTP para evitar introducir imágenes grandes en su contrato.

## API

| Método y ruta | Función |
| --- | --- |
| `GET /api/capture` | Fuente actual, estado, configuración y último frame |
| `POST /api/capture/file` | Multipart con `file` y `capture_fps`; sube y reproduce |
| `POST /api/capture/screen` | JSON con `capture_fps` y `name`; abre el adaptador |
| `POST /api/capture/{id}/screen-frame` | Imagen JPEG de la superficie seleccionada |
| `GET /api/capture/{id}/frame?after=N` | Último JPEG, o 204 si no hay un frame nuevo |
| `POST /api/capture/{id}/stop` | Detiene la fuente y descarta el preview |

El JPEG expone `X-Frame-Id`, `X-Frame-Timestamp` y `X-Capture-Fps`. Las peticiones de una captura anterior se rechazan con 409. Intentar abrir otra fuente mientras una está activa también devuelve 409. Los errores de validación de fuente producen 422; formatos no admitidos, 415; límites de tamaño, 413.

## Archivos y ejecución

Se añade `backend/app/capture_engine/`, `backend/tests/test_capture.py`, `backend/scripts/create_sample_video.py`, `frontend/src/capture/`, `frontend/src/styles/capture.css` y `frontend/tests/capture.spec.ts`. Se actualizan dependencias, arranque y handshake de FastAPI, límite de subida en Nginx, portada, navegación y página en directo. `app.md` se conserva.

Arranque: `docker compose up --build -d --wait`. Instrucciones completas de ejecución local, generación de muestra y pruebas en [README.md](../README.md).

## Validación

Antes de implementar esta fase se repitieron las 8 pruebas de backend y las 5 de navegador de fase 1, todas correctas.

La suite de backend ahora verifica muestreo con reloj controlado, ausencia de duplicados, frame más reciente de pantalla, timeout por inactividad, JPEG real, conflictos entre fuentes, identificadores antiguos, fin de vídeo en tiempo real, limpieza de archivos y liberación al cerrar la aplicación.

Las pruebas de navegador añaden reproducción de vídeo real, continuidad al navegar, final de archivo, rechazo de vídeo corrupto, cancelación del selector y captura de una pestaña dedicada. El selector de prueba de Chromium limita la selección a esa pestaña; no captura el escritorio personal.

La prueba nativa utiliza el canal `chromium` completo en modo headless; el binario reducido `chromium-headless-shell` no admite `getDisplayMedia`. Esta elección afecta solo a las pruebas. En la aplicación el usuario sigue eligiendo la superficie mediante el selector normal del navegador.

Resultado final, 17 de septiembre de 2026: **15 pruebas de backend y 8 de navegador superadas**; compilación TypeScript/Vite y comprobación de formato correctas; los tres contenedores saludables. Se revisaron capturas de escritorio y móvil. La prueba nativa verifica tanto el botón de parada como el cierre de la pestaña compartida. No se observaron errores de ejecución en los logs finales del backend. Persisten dos avisos de deprecación de las dependencias de pruebas Starlette/AnyIO ya presentes en fase 1.

## Límites actuales y siguiente fase

- Una fuente global, un proceso backend, sin sesiones persistidas ni usuarios separados.
- Archivos hasta 256 MB y 8.294.400 píxeles por frame. El códec debe estar disponible en la distribución de OpenCV/FFmpeg.
- Reproducción basada en FPS constante; VFR, pausa, búsqueda, bucle y audio no forman parte de esta fase.
- Pantalla hasta 1920 × 1080; preview hasta 1280 × 720. La reducción de resolución debe revisarse al incorporar OCR.
- FPS configurables de 1 a 15. Se muestran como objetivo de captura; la medición de FPS reales y latencia del pipeline pertenece a fase 3.
- Pantalla detenida por permiso revocado, cierre/recarga de la pestaña emisora, error de envío o 15 segundos sin frames. El navegador puede ralentizar tareas en segundo plano.
- No hay reconocimiento de mesa, cartas, stacks ni recomendaciones.

La fase 3 añadirá `FrameQueue`, `FrameProcessor` y el contrato del `VisionEngine`, con colas acotadas, prioridad al estado reciente y métricas de captura/procesamiento. No se anticipan esas funcionalidades aquí.

## Referencias

- [OpenCV VideoCapture](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html).
- [MDN: getDisplayMedia y permisos del navegador](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia).
- [FastAPI: subida de archivos](https://fastapi.tiangolo.com/tutorial/request-files/).
- [Chromium: selector de pestaña para pruebas](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/chrome/common/chrome_switches.h).
