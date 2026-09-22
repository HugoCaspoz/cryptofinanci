# Fase 5 — Detección de cartas en directo

## Construido y alcance

El pipeline ya reconoce cartas de Hero y board a partir de los **píxeles del frame**. Las observaciones incluyen `rank`, `suit` y `confidence`; un filtro temporal confirma cambios antes de modificar las cartas mostradas y emitir eventos. La captura continúa de forma independiente del reconocimiento, utilizando la cola limitada de la fase 3.

La validación utiliza **Zeros demo**, una baraja sintética de 52 cartas creada con OpenCV. No hay capturas ni referencias de una plataforma real en el proyecto. El resultado no demuestra precisión en PokerStars, GGPoker u otra sala. La interfaz identifica expresamente las referencias de demostración.

El detector admite perfiles de referencias externas para una única plataforma y el layout de 1920 × 1080 y seis asientos de la fase 4. El formato está documentado en [card_templates/README.md](../backend/card_templates/README.md). Los perfiles externos exigen nombre de plataforma coincidente y calibración manual confirmada.

## Reconocimiento visual

`VisionEngine` carga una copia validada del layout, su revisión y el perfil de referencias al iniciar la captura. Las lecturas posteriores usan esa copia; editar el layout o los PNG no cambia una captura en curso. La carga se realiza fuera del event loop, antes de arrancar la fuente.

Para cada frame:

1. Se comprueba que la resolución coincida exactamente con el layout.
2. Se recortan `hero_cards` y `board` sobre el frame original, antes de reducir el JPEG de previsualización.
3. Una región se considera vacía solo si al menos el 98,5% coincide con el color de fondo configurado, dentro de su tolerancia por canal. Negro, un dorso u otra imagen desconocida no se convierten automáticamente en vacío.
4. Se segmentan rectángulos claros mediante HSV y contornos. Se rechazan formas incompatibles y cartas recortadas por los límites de la región. Hero requiere dos cartas; el board, tres, cuatro o cinco.
5. Cada carta se normaliza a 96 × 128. Se compara la zona superior del índice y la inferior del palo contra las 52 referencias mediante correlación normalizada de OpenCV. Se utiliza la menor puntuación de ambas zonas. El procedimiento se apoya en [la comparación de plantillas de OpenCV](https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html).
6. Se exige puntuación mínima de 0,86 y margen mínimo de 0,035 frente a la segunda referencia. Lecturas parciales, ambiguas o duplicadas se marcan como desconocidas. La misma carta en Hero y board invalida la observación conjunta.

Los umbrales se han probado con la baraja sintética. `confidence` es una puntuación de similitud, **no una probabilidad calibrada**. El filtro conserva una puntuación conservadora durante la confirmación. Cartas con otra tipografía o distribución visual necesitan sus propias referencias y validación independiente; no hay un modelo universal entrenado.

## Confirmaciones y eventos

El componente `CardTracker`, dentro de `game_state_engine`, exige **tres observaciones consecutivas con las mismas cartas**. Cada observación procede de un frame procesado distinto. Un resultado desconocido, un detector no disponible o una separación superior a 2,5 segundos interrumpe la racha. No se procesa vídeo futuro para confirmar una lectura actual.

Las cartas confirmadas permanecen ante lecturas desconocidas; la interfaz muestra que son el último resultado conservado. Una lectura vacía requiere también tres observaciones. El orden de las dos cartas de Hero no provoca un evento nuevo; el orden del board sí se conserva. Antes de publicar se comprueba que las cartas propuestas no dupliquen las cartas retenidas de la otra región.

| Cambio confirmado | Evento |
| --- | --- |
| Aparecen o cambian las dos cartas de Hero | `HOLE_CARDS_DETECTED` |
| Board vacío → tres cartas | `FLOP_DEALT` |
| Tres → cuatro, conservando las tres anteriores | `TURN_DEALT` |
| Cuatro → cinco, conservando las cuatro anteriores | `RIVER_DEALT` |
| Otra actualización del board, salto o corrección | `BOARD_CARDS_UPDATED` |
| Hero confirmado → vacío confirmado | `HERO_CARDS_CLEARED` |
| Board confirmado → vacío confirmado | `BOARD_CARDS_CLEARED` |

Si la captura empieza con cinco cartas visibles, se registra una actualización del board: no se inventan los tiempos del flop y del turn. Cada evento contiene un ID incremental por captura, tipo, cartas, `frame_id` y `timestamp` de fuente del frame que completó la confirmación. Ese timestamp representa cuándo se confirmó visualmente, no el instante exacto del reparto.

No se emiten eventos cuando las cartas siguen iguales, aunque cambie la puntuación. El vaciado de cartas **no implica fold, fin de mano ni nueva mano**; esas inferencias quedan para fases posteriores. Una reaparición tras un vaciado confirmado sí constituye una nueva observación de cartas.

Se retienen como máximo 40 eventos, los dos conjuntos de cartas y sus candidatos. El contador total puede seguir aumentando. Iniciar una captura nueva reinicia cartas, candidatos e historial. El fin de archivo o la parada conserva el último resultado para inspección, identificado como finalizado o detenido en la interfaz.

## API e interfaz

`GET /api/capture` amplía `observation_state`:

```text
recognition_available
observations_seen
last_frame_id
cards:
  detector_status, profile, demo, layout_revision
  hero: cards[], status, confirmations, required_confirmations
  board: cards[], status, confirmations, required_confirmations
  events[], event_count
```

`recognition_available` indica que existe un detector configurado para la resolución recibida; no garantiza que sus regiones sean legibles. `detector_status` distingue perfil o layout ausentes, plataforma diferente, layout sin calibrar, resolución incorrecta y duplicados. El estado de cada región distingue espera, confirmación pendiente, confirmada, vacía, desconocida y conflicto.

El panel **Cartas observadas** muestra ambas zonas, puntuaciones, avisos y eventos, con diseño adaptable a móvil. Se actualiza mediante el sondeo HTTP de captura ya existente, cada 500 ms. El WebSocket mantiene el handshake y ping/pong; el transporte general de eventos y la interfaz completa de manos corresponden a las fases 8 y 11.

Ambos modos muestran exclusivamente observaciones descriptivas. No se calculan ni muestran recomendaciones, equity o decisiones. El handshake continúa declarando `strategy_available: false`.

## Archivos

Nuevos:

- `backend/app/card_detector/{models,demo,templates,detector}.py` y `__init__.py`.
- `backend/app/game_state_engine/{card_tracker,card_state}.py`.
- `backend/card_templates/README.md` y `backend/scripts/create_card_video.py`.
- `backend/tests/test_card_detector.py`, `test_card_state.py`, `test_card_capture.py`.
- `frontend/src/cards/{types,CardPanel}` y `frontend/src/styles/cards.css`.
- `frontend/tests/card-scenario.ts` y este documento.

Actualizados: observaciones de visión y estado, creación de procesadores y captura, configuración, salud y handshake; contratos TypeScript, página Live, panel de depuración, portada, versión, estilos y pruebas existentes; Compose, `.env.example` y README. No se modifica `app.md` ni se añaden dependencias.

## Ejecutar y probar

Desde la raíz, con Docker Desktop activo:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_sample_video.py
backend/.venv/Scripts/python backend/scripts/create_layout_video.py
backend/.venv/Scripts/python backend/scripts/create_card_video.py
backend/.venv/Scripts/python -m pytest backend -q -o cache_dir=.pytest_cache_phase5
```

Desde `frontend/`:

```powershell
npm run build
npm run format:check
npm test
```

Las pruebas de navegador necesitan el layout `Zeros demo`, los tres vídeos generados, `CARD_TEMPLATE_DIR` vacío y ninguna captura activa. No edites el layout durante ellas. Si personalizas las regiones, regenera los vídeos; las zonas de cartas deben permitir dos y cinco cartas completas, respectivamente.

Para comprobarlo manualmente, abre http://localhost:5173/live, reproduce `sample_data/cards-demo.avi` y observa el panel:

| Tiempo de fuente | Imagen sintética |
| --- | --- |
| 0–1 s | Zonas vacías |
| 1–4 s | Hero A♠ J♥ |
| 4–7 s | Flop J♠ 7♣ 4♦ |
| 7–10 s | Turn 2♥ |
| 10–13 s | River 10♣ |
| 13–14 s | Regiones negras: lectura desconocida, se conserva lo confirmado |
| 14–17 s | Mismas cartas: no se repiten eventos |
| 17–19 s | Vacío confirmado en ambas regiones |
| 19–22 s | Reaparece A♠ J♥; nuevo evento de observación |

Con 5 FPS, las confirmaciones suelen llegar unos 0,4 segundos después del cambio visible, más procesamiento y transporte. El resultado esperado son siete eventos, Hero con dos cartas y board vacío al terminar. El generador únicamente crea imágenes; el detector no recibe su secuencia ni metadatos sobre las cartas.

## Validación y límites

Antes de implementar esta fase se arrancó la fase 4 y pasaron sus 44 pruebas de backend y 10 de navegador. Las pruebas nuevas comprueban las 52 cartas con reducción, ruido y compresión JPEG; regiones vacías/desconocidas/recortadas, ambigüedad, cartas duplicadas, perfiles y layout congelado; confirmaciones, interrupciones, saltos de street, correcciones e historial limitado; y vídeo real procesado por el pipeline en ambos modos.

Las pruebas de navegador verifican la secuencia de 22 segundos contra el backend real, las siete emisiones únicas, desaparición y reaparición, ausencia de errores JavaScript y diseño sin desbordamiento horizontal en móvil. Se revisaron visualmente capturas de escritorio y móvil.

Resultado final del 18 de septiembre de 2026: **109 pruebas de backend y 11 de navegador superadas**, compilación TypeScript/Vite y formato correctos. Los tres servicios de Compose están saludables y `/health` informa de la fase 5. No aparecen errores de ejecución en los logs revisados. Se mantienen los dos avisos de deprecación de Starlette/AnyIO ya presentes en fases anteriores.

El reconocimiento inicial exige cartas completas, verticales, separadas, de fondo claro y con el índice arriba y el palo debajo. No contempla perspectiva de cámara, abanicos, dorsos, animaciones, fondos vacíos complejos ni todos los diseños de baraja. Los falsos positivos siguen siendo posibles; tres lecturas iguales reducen fluctuaciones, pero no corrigen un error visual sistemático. Hace falta un dataset real independiente para medir precisión y ajustar cada perfil.

No hay reconstrucción de manos, detección de turnos de acción ni almacenamiento duradero de eventos. El registro de 40 entradas no sustituye una hand history. No se ha validado ejecución continua durante ocho horas.

La fase 6 implementará OCR de nicknames, stacks, apuestas, bote y ciegas con confianza y estabilización temporal.
