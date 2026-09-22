# Fase 4 — Configuración de la mesa

## Construido

Un layout persistente para frames de **1920 × 1080 y seis asientos**, con 29 regiones: `hero_cards`, `board`, `pot`, `dealer_button`, `blinds` y `nickname`, `stack`, `bet`, `action` para cada jugador. Se entrega como **Zeros demo**, pendiente de calibración. No se ha recibido una plataforma ni una captura real de referencia; las coordenadas iniciales son una plantilla de demostración.

El editor de `/live` permite nombrar la plataforma, seleccionar cualquier región, modificar sus coordenadas, ver los cambios al instante y guardar. El usuario puede confirmar que ha comprobado todas las regiones; cambiar geometría o nombre vuelve a marcar la calibración como pendiente. Esa confirmación es manual, no una validación automática de visión.

El overlay SVG muestra todas las zonas, diferencia las regiones de mesa y jugadores, destaca la seleccionada y permite ocultar etiquetas o desactivarlo completo. Usa las dimensiones originales incluidas en la misma respuesta HTTP que el JPEG (`X-Frame-Width` y `X-Frame-Height`), sin depender del sondeo separado del estado. El JPEG puede ser reducido a 1280 × 720, pero el sistema de coordenadas sigue siendo de 1920 × 1080.

Imagen y overlay comparten contenedor, centrado y proporción. Se conserva la alineación con el espacio vacío producido por el límite de altura, así como al cambiar de tamaño la ventana. Si la captura no tiene la resolución exacta o el borrador tiene coordenadas inválidas, se oculta el overlay y se explica el motivo. No se estiran regiones para aparentar compatibilidad.

No se cambia el pipeline de análisis ni se reconocen cartas. `table_detector` gestiona regiones configuradas; su nombre no implica detección automática. Ambos modos continúan sin recomendaciones.

## Archivo y contrato

`backend/table_layouts/platform_1920x1080.json` contiene:

- `version: 1`, `platform`, `width: 1920`, `height: 1080`, `calibrated`.
- `regions`: las cinco zonas generales.
- `players`: seis objetos ordenados por asiento, cada uno con sus cuatro zonas.
- Cada rectángulo: `x`, `y`, `width`, `height`, en píxeles enteros de origen. Origen arriba a la izquierda; X crece a la derecha e Y hacia abajo. Un futuro recorte usará `[y:y+height, x:x+width]`.

Se rechazan dimensiones nulas, coordenadas negativas, regiones fuera del frame, valores fraccionarios, tipos incorrectos, campos inesperados y zonas o asientos ausentes. Las regiones pueden solaparse; el solapamiento puede ser deliberado y debe revisarse visualmente.

| Operación | Resultado |
| --- | --- |
| `GET /api/table-layout` | JSON validado, `ETag` y `Cache-Control: no-store` |
| `PUT /api/table-layout`, con `If-Match` del GET | Valida y guarda el documento completo; devuelve JSON y nueva revisión |
| Falta `If-Match` | 428 |
| Otra escritura cambió la revisión | 409; no se sobrescribe el archivo |
| Documento propuesto inválido | 422; el archivo se conserva |
| Archivo ilegible/corrupto o error de escritura | 503 con mensaje visible en la interfaz |

La ruta del archivo es fija y no procede del navegador. Las operaciones de archivo usan rutas síncronas ejecutadas por FastAPI fuera del event loop. Un lock protege lecturas/escrituras concurrentes en el proceso; se escribe un temporal en el mismo directorio, se vacía y sincroniza, y se reemplaza atómicamente el archivo. Si falla el reemplazo, se conserva el original y se retira el temporal.

La aplicación sigue requiriendo **un solo worker de backend**, como la captura global. No hay coordinación de escrituras entre varios procesos. No edites el JSON directamente mientras otra pestaña está guardándolo. Los cambios manuales se validan al recargar; un JSON inválido no se sustituye silenciosamente por valores predeterminados.

Docker incorpora el layout y Compose monta el directorio local como escritura persistente. En Linux, el directorio montado debe ser escribible por el usuario `zeros` del contenedor. No se usa PostgreSQL para esta configuración.

## Archivos

Nuevos:

- `backend/app/table_detector/{layout,store,routes}.py` y `__init__.py`.
- `backend/table_layouts/platform_1920x1080.json`.
- `backend/tests/test_layout.py` y `backend/scripts/create_layout_video.py`.
- `frontend/src/table/{types,useTableLayout,LayoutPanel,TableOverlay}` y `frontend/src/styles/table.css`.
- Este documento.

Actualizados: construcción y rutas de FastAPI, versión y fase del handshake/salud, cabeceras de preview, Dockerfile y Compose; preview y página Live, portada, navegación y estilos; pruebas API y navegador; README. `app.md` y las dependencias permanecen sin cambios.

## Ejecutar y comprobar

Desde la raíz:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_sample_video.py
backend/.venv/Scripts/python backend/scripts/create_layout_video.py
backend/.venv/Scripts/python -m pytest backend -q -o cache_dir=.pytest_cache_phase4
```

Desde `frontend/`, con los servicios arrancados:

```powershell
npm run build
npm run format:check
npm test
```

Prueba manual:

1. Abre http://localhost:5173/live y reproduce `sample_data/table-layout-demo.avi`.
2. Activa **Mostrar regiones**: deben aparecer 29 rectángulos. Selecciona regiones de mesa y jugadores y comprueba la resaltada.
3. Cambia X o ancho: el borrador se actualiza. Un rectángulo fuera de los límites oculta el overlay y bloquea Guardar.
4. Guarda una coordenada válida, recarga la página y comprueba que permanece. **Recargar layout** descarta cambios todavía no guardados.
5. Reduce la ventana o utiliza móvil: las regiones siguen alineadas. Las etiquetas se pueden ocultar para apreciar los bordes.
6. Reproduce `capture-demo.avi`, de 960 × 540, y activa el overlay: debe aparecer el aviso de resolución incompatible, sin rectángulos.
7. Para calibrar una plataforma real, usa una captura de composición fija, nombra la plataforma y comprueba las 29 zonas antes de confirmar la calibración manual.

El vídeo sintético dura tres segundos y se conserva su último frame como referencia. Se genera a partir del layout actual, por lo que sirve para comprobar geometría y transporte; **no demuestra precisión sobre ninguna sala real**.

## Validación

Antes de implementar, se arrancó la fase 3 y pasaron sus 26 pruebas de backend y 8 de navegador.

Las pruebas nuevas de backend comprueban esquema completo, límites de píxeles y tipos, persistencia tras recrear la aplicación, conflictos entre escritores, guardado atómico fallido y archivo corrupto. Las de navegador comprueban las 29 regiones sobre el JPEG real de backend, sus dimensiones de origen, alineación geométrica con un error inferior a un píxel en escritorio y móvil, edición, validación, guardado, recarga, conflicto entre pestañas y recuperación tras errores de carga.

Resultado final del 18 de septiembre de 2026: **44 pruebas de backend y 10 de navegador superadas**. Compilación TypeScript/Vite y formato correctos. Los tres servicios de Compose están saludables. Se revisaron capturas de escritorio y móvil; se separaron las zonas de Hero en la plantilla y se movió el aviso de fin de vídeo fuera de la imagen para no tapar las ciegas.

Durante una ejecución inicial, Chromium se cerró inesperadamente en la prueba de captura nativa. El caso aislado y las dos ejecuciones completas posteriores pasaron sin cambiar la lógica de captura. No se identificó la causa del cierre; no hubo un fallo asociado del backend en los registros revisados. Persisten los dos avisos de deprecación de Starlette/AnyIO ya presentes en la fase anterior.

## Limitaciones y siguiente fase

Solo se permite este tamaño y seis asientos. El nombre de plataforma es descriptivo; no activa detección automática. Aún falta seleccionar y calibrar una plataforma real. Cambios de tema, zoom, composición o posición de la mesa requieren revisar las coordenadas. Una resolución coincidente por sí sola no garantiza una mesa bien encuadrada.

El botón del dealer tiene una sola región fija en esta fase: para una mesa real debe abarcar sus posibles ubicaciones; localizar su posición precisa y asociarla a un asiento vendrá después. No se infieren posiciones ni acciones.

El borrador del editor es local a la página y se pierde al navegar fuera; el contenido guardado permanece. Otras pestañas deben recargar para leerlo. No hay historial de versiones ni editor por arrastre.

La fase 5 abordará reconocimiento de cartas de Hero y del board y estabilidad temporal sin eventos duplicados, usando el layout calibrado y referencias de cartas. El OCR queda para la fase 6.
