# Fase 25 - Latencias por etapa

## Revisión anterior y alcance

Se revisaron la fase 24, el contrato de FramePipeline, los workers de análisis y la suscripción WebSocket. La entrega anterior había validado 583 pruebas de backend y los escenarios de explicaciones, entrenamiento y revisión; esas pruebas se conservan en la regresión de esta fase.

Se instrumenta el recorrido existente sin cambiar FPS, tamaño de cola, reconocimiento, estrategia, permisos ni proveedor del explicador. No se introducen descartes para mejorar las cifras. La fase 26 se ocupará del muestreo adaptativo.

## Qué se ha construido

En /live, Depuración del pipeline contiene una tabla de latencias por etapa con último valor, media, P95, muestras retenidas y frame de la última muestra. Los objetivos se interpretan explícitamente como objetivos P95: visión <200 ms, estado <50 ms e interfaz <100 ms. Son metas de ingeniería, no garantías por frame ni condiciones de aprobación artificial de las pruebas.

Los acumuladores del servidor y navegador guardan como máximo 128 duraciones por etapa y un contador total; P95 es el percentil de rango más cercano (ceil(0,95 * n)). No es una ventana temporal de cinco segundos: esa ventana sigue siendo exclusiva de los FPS. Se rechazan duraciones negativas o no finitas. Las muestras vuelven a empezar en una captura nueva; los valores del servidor quedan visibles al finalizar.

## Definiciones de medida

| Campo de pipeline.latencies | Qué mide |
| --- | --- |
| capture | Lectura/decodificación en el adaptador del backend. En archivo, grab/retrieve del muestreo elegido; en pantalla, decodificación del JPEG recibido. No mide selección de pantalla, codificación del navegador, subida ni intervalo entre muestras. |
| vision | VisionEngine.observe dentro del worker: cartas, OCR y observación de acciones. Incluye muestras donde OCR decide no volver a leer. |
| preview | Redimensionamiento y preparación JPEG tras visión. |
| state | GameStateEngine.accept, incluidas sus proyecciones y eventos síncronos. No incluye escrituras ni motores asíncronos. |
| publish | Callback que prepara el estado: flush de decisiones, reconstrucción, persistencia de manos/eventos, actualización de rivales/preflop y envío de trabajos a los motores. Incluye state. |
| total_backend | Desde el inicio de lectura/decodificación del frame hasta terminar ese callback y quedar listo para publicar el snapshot. Incluye esperas de adaptador/cola/worker. No incluye serialización/transporte WebSocket, descarga JPEG ni pintado. |
| equity | Trabajo devuelto por el motor matemático, incluida espera de su llamada en el executor. Puede devolver comprobaciones/avisos sin equity numérica. Resultados descartados por generación y excepciones no añaden muestras. |
| strategy | Cálculo de una estrategia ready que se ha podido archivar; el valor es su tiempo de cálculo, sin sumar persistencia. |
| equity_total | Desde el origen del frame de ese trabajo hasta devolver el resultado matemático aceptado. |
| strategy_total | Desde el origen del frame de ese trabajo hasta archivar la estrategia. |

Los motores se ejecutan en paralelo al pipeline y pueden terminar sobre un frame anterior al de la imagen actual. No se suman sus duraciones al total ni entre sí. Una captura mantiene solo 128 orígenes de frames como pares de identidad y reloj, sin conservar sus imágenes. Si un origen ya se expulsó, se puede medir el cálculo pero no se añade un total inventado: la fila total conserva su última muestra disponible y su frame. Los callbacks de otro scope de captura se ignoran.

El servidor utiliza relojes monotónicos para los intervalos. Los timestamps de fuente (segundos del vídeo) siguen siendo exclusivos de observación y reconstrucción, nunca se restan del reloj del sistema.

## Medida de la interfaz

LiveProvider toma performance.now al recibir el mensaje, antes de parsear el snapshot. CaptureProvider conserva la marca solo si ese estado se acepta según instancia/revisión. Tras el commit se usan dos requestAnimationFrame para aproximar un pintado completado. No es una medida exacta de GPU/pantalla ni incluye el JPEG que llega por HTTP.

Solo se muestrean entregas que permanecen vigentes y visibles hasta esa aproximación del pintado. Las sustituidas, desconectadas o interrumpidas por ocultar la pestaña se cancelan. No se mezclan capturas ni reconexiones; una actualización del propio medidor no inicia otra muestra y no crea un bucle de snapshots o peticiones.

Esta fila mide snapshots presentados, no todos los frames capturados. El WebSocket sigue coalesciendo actualizaciones y el medidor no consulta GET /api/capture ni envía telemetría al servidor. No se resta un reloj del navegador de uno del backend ni se afirma disponer de latencia completa desde la pantalla original.

## Consistencia y acceso

El snapshot final de un frame se publica después de registrar sus contadores y tiempos. Antes se notificaba antes del incremento de procesados, por lo que la métrica podía ir un frame por detrás. Se mantiene la revocación inmediata de la revisión al detectar otra mano, antes de esperar persistencia.

Los campos añadidos solo contienen tiempos, contadores y frame IDs. No exponen recomendaciones, rangos ni evaluaciones en LIVE_REAL_MONEY. No hay endpoints nuevos ni migración de base de datos. Se mantienen los campos históricos de PipelineMetrics y el contrato de FrameProcessor con un campo timings opcional para procesadores personalizados.

## Archivos

- Backend: pipeline_engine/latency.py y metrics.py; instrumentación de processor.py, pipeline.py y capture_engine/{source,file_source,screen_source,engine}.py.
- Motores: poker_engine/service.py y strategy_engine/strategy_service.py reportan tiempos sin alterar su estrategia.
- Frontend: live/{latency,LiveProvider}, capture/{CaptureProvider,PipelineDebug,types}, styles/pipeline.css.
- Versión 0.25.0/fase 25 en version.py, test_api.py, App.tsx y Dashboard.tsx.
- Pruebas: create_opponent_video.py añade un margen opcional al turno sintético; backend/tests/test_latency.py; frontend/tests/latency.spec.ts y comprobaciones de trabajos asíncronos en training-tests/strategy.spec.ts. README.md y este documento.

## Ejecutar y probar

```powershell
docker compose up --build -d --wait
```

Abrir http://localhost:5173/live, iniciar una fuente y desplegar Depuración del pipeline. Visión y estado aparecen al procesar frames. Para tiempos de estrategia, en TRAINING confirma los contextos de una mano como en la demo de la fase 24; no se inventan muestras de estrategia cuando falta un resultado ready.

Backend con una base PostgreSQL exclusiva de pruebas, creada previamente:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase25_checks zeros-backend-tests
```

Desde frontend/:

```powershell
npm run build
npm run format:check
```

La prueba de navegador de captura requiere una instancia aislada. Puede usarse seed_timeline_review.py --serve en la imagen de tests y una interfaz auxiliar, como en la fase 24. Con la URL de esa interfaz:

```powershell
$env:E2E_BASE_URL = 'http://127.0.0.1:5174'
$env:E2E_BROWSER_CHANNEL = 'msedge'
$env:LATENCY_E2E = '1'
npx playwright test tests/latency.spec.ts --workers=1
```

LATENCY_E2E habilita el caso que abre una captura sintética; sin esa variable solo corre el test puro del acumulador. La prueba envía JPEGs de 64 x 64 sin solicitar la pantalla del usuario. Comprueba filas, objetivos, contadores, actualización WebSocket sin polling y escritorio/móvil. La prueba de entrenamiento adjunta latency-metrics (JSON) con el estado observado durante el turno de Hero; para la demo se usa el vídeo generado con el mismo OpenCV de Docker.

## Validación

- Backend completo Docker, Tesseract y PostgreSQL exclusivo: **590/590 pruebas correctas**, sin omisiones, en 234,14 s.
- Regresión focal inicial de pipeline y servicios: 45 correctas, 2 PostgreSQL omitidas en local (cubiertas luego en Docker). Ventanas, relojes, callbacks y reinicio: 18/18 correctas en local.
- Compilación TypeScript/Vite y formato: correctos.
- Navegador general, acumulador, captura sintética y timeline/explicaciones: **9/9 correctas**, 26,1 s, con escritorio y móvil. Tras descartar medidas UI interrumpidas por ocultar la pestaña se repitieron los dos casos de latencia: **2/2 correctos**.
- Capturas de la tabla revisadas visualmente; en el caso sintético de 64 x 64 no se aplica OCR, por lo que no se usa como benchmark de visión real.
- Entrenamiento con vídeo Docker y margen de 4 s: **1/1 correcto**, 1,2 min. Verifica explicación durante el turno, telemetría de ambos motores, origen del frame de estrategia, archivo/evaluación posterior y escritorio/móvil.
- Compose principal actualizado y sano en fase 25, LIVE_REAL_MONEY y PostgreSQL, sin captura activa. Instancias temporales detenidas tras validar.

Referencia de esa ejecución de entrenamiento (1920 x 1080, 5 FPS solicitados, vídeo sintético con OCR; valores del servidor al detenerla):

| Etapa | Muestras de la ventana | Media ms | P95 ms |
| --- | ---: | ---: | ---: |
| Captura/decodificación | 128 de 333 | 14,03 | 29,39 |
| Visión con OCR | 126 | 497,07 | 855,34 |
| Estado | 126 | 1,09 | 1,58 |
| Preparación/persistencia | 126 | 21,69 | 68,97 |
| Total backend hasta estado listo | 126 | 653,40 | 1003,16 |
| Motor matemático | 21 | 140,97 | 188,18 |
| Estrategia | 1 | 584,68 | 584,68 |

La visión supera el objetivo de 200 ms. Un único trabajo de estrategia no permite caracterizar su rendimiento; se muestra su duración sin presentarlo como un benchmark general. Estos resultados dependen de la máquina/carga y no validan una plataforma real. En la prueba sintética de 64 x 64, la captura visual revisada mostró P95 UI de 41,2 ms; es otro escenario y no se suma al total de esta tabla.

## Límites y siguiente fase

No hay medición completa desde el sensor/pantalla original ni del coste del selector, subida, red, JPEG HTTP o GPU. El medidor UI puede omitir entregas reemplazadas antes del pintado; solo caracteriza muestras presentadas en primer plano. Las estadísticas son en memoria por captura, sin exportación histórica automática ni calibración de rendimiento por plataforma real. Una media/P95 baja no demuestra que la observación sea correcta.

Se muestran los objetivos superados tal cual, sin debilitar OCR, colas ni reglas de consistencia para reducir tiempos. La fase 26 prevista añadirá muestreo inteligente ante cambios observados; no se implementa en esta entrega.


## Margen de la demo de entrenamiento

La demo original deja un turno corto de Hero y el procesamiento OCR puede hacer que la prueba llegue al botón cuando el turno ya ha terminado. Se añade --decision-hold-seconds (0-4, predeterminado 0) al generador: extiende solo el tiempo de ese turno en el vídeo sintético y desplaza sus eventos posteriores. Las reglas y FPS de la aplicación no cambian.

```powershell
docker run --rm -v C:/code/poker/backend/scripts:/app/scripts:ro -v C:/code/poker/sample_data:/samples zeros-backend-tests python scripts/create_opponent_video.py --decision-hold-seconds 4 --output /samples/opponents-demo.avi
```

Con esta variante el vídeo dura 72 s. El generador sin la opción mantiene los 68 s originales. La primera prueba detectó la desaparición correcta del panel al actuar Hero; se amplió el margen de la fixture para poder verificar la interacción de explicación antes de esa retirada.

El margen se limita a 4 s para respetar la caducidad de evidencia de acciones (12 s). Una prueba con 8 s extendía el turno más allá de esa ventana antes de confirmar el fold; el sistema lo dejó sin acción atribuida. Se preserva ese control y se usa una fixture dentro de su contrato temporal.
