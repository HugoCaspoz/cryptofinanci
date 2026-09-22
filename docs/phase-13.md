# Fase 13 — Motor preflop

El nuevo módulo `strategy_engine/` produce `StrategyResult` a partir de GameState, un contexto confirmado de la mano y tablas configurables. No lee imágenes ni modifica el estado observado. El motor matemático y su simulación de equity siguen separados; esta baseline no transforma una equity contra rangos aleatorios en una recomendación.

## Alcance y datos necesarios

Se cubre la **primera decisión preflop de Hero** en mesas de 2–6 jugadores: bote sin abrir, con limpers o frente a una subida completa. El turno observado debe coincidir con el turno reconstruido. Antes de evaluar se comprueban:

- Mano activa e identidad de mano/captura, dos cartas de Hero y board vacío confirmado.
- Asientos que recibieron cartas, botón y numeración horaria, confirmados manualmente para esta mano. Incluye jugadores que ya hicieron fold.
- Ciegas, bote, stacks y apuestas con evidencia confirmada de los últimos 2,5 segundos de fuente, en la misma unidad.
- Antes totales en BB y convención del bote, confirmados manualmente. Los antes no forman parte de la apuesta que hay que igualar.
- Historial completo de acciones voluntarias hasta el momento de aplicar la configuración. `[]` es una afirmación explícita de que aún no hubo ninguna, no una inferencia por falta de eventos.

La aplicación todavía no detecta automáticamente botón/posiciones/antes. No permite sustituir las lecturas monetarias o cartas por números inventados mediante esta configuración. Si las contribuciones reconstruidas más los antes no coinciden con el bote, se abstiene. También contrasta cada apuesta y los folds observados con el historial.

Las posiciones se calculan sobre los asientos confirmados, con tratamiento específico de heads-up: botón/SB actúa primero preflop. En 6-max se usan UTG, HJ, CO, BTN, SB y BB; en mesas menores se eliminan las primeras posiciones. La reconstrucción respeta el orden y el mínimo de subida completa (último incremento). Referencia de reglas: [PokerStars, reglas y ciegas heads-up](https://www.pokerstars.com/help/articles/poker-rules-master/).

## Tablas y resultado

Cada regla delimita escenario, posiciones de Hero, posiciones del agresor opcionales, número de jugadores al reparto, bandas de stack efectivo, tamaño de subida previa y antes. Los límites son inclusivos: evita solapar bandas en sus extremos. Debe coincidir **exactamente una regla**; si faltan reglas o coinciden varias, no se recomienda una acción.

Los rangos `raise_range` y `call_range` admiten la notación de la fase 12 (`AA,KK,AKs`, `AKo`, `AsKh`, `random`). Pueden estar vacíos. Deben ser disjuntos, sin frecuencias mixtas ni pesos distintos de uno. El resto del rango hace fold si hay una apuesta pendiente; cuando no hay coste de igualar, el resultado es check.

El stack efectivo para seleccionar la tabla incluye stack restante **más la apuesta ya comprometida en preflop**, después de descontar antes. Se usa `min(total Hero, máximo total de rivales no retirados) / BB`. Este agregado multiway no sustituye un análisis específico contra cada rival. La fase 12 sigue mostrando su propio stack efectivo restante y SPR actual.

El sizing es la apuesta **total** de la calle, no el incremento. En aperturas/aislamientos se usa `open_to_bb + callers × extra_per_caller_bb`; frente a una subida, `raise_to_bb × raise_multiplier + callers × extra_per_caller_bb`. Se impone el mínimo legal y el límite de fichas de Hero. Un tamaño que consume su stack se identifica como `ALL_IN`; si no alcanza a subir sobre la apuesta actual, no se convierte silenciosamente la subida de la tabla en un call. `additional_bb` expresa las fichas adicionales necesarias.

La tabla de ejemplo, creada para probar el flujo, cubre 20–200 BB, antes cero y una subida previa de hasta 4 BB. No es una tabla GTO ni está calibrada contra un solver. `confidence` es deliberadamente `null`: la confianza del OCR no prueba la calidad estratégica de una tabla.

```json
{
  "status": "ready",
  "action": "RAISE",
  "sizing_bb": 2.5,
  "additional_bb": 2.5,
  "sizing_kind": "total_street",
  "confidence": null,
  "basis": "configured_baseline_not_gto",
  "rule_id": "open-early"
}
```

El resultado real incluye motivo, contexto aplicado, mano, frame y tiempo de fuente. Estados incompletos o no cubiertos devuelven `status: unavailable`, motivo y `action: null`. No hay EV, explotación de rivales, solver, decisiones posteriores de Hero, botes con varias subidas ni respuestas a all-ins/reaperturas cortas. La sugerencia de un all-in propio al aplicar un sizing no implica resolver los all-ins anteriores del historial.

## Flujo temporal y archivo privado

Al aplicar el contexto se comprueban `capture_id`, `hand_id` y `state_revision`; una petición de una vista anterior devuelve 409. El historial manual queda anclado al último número de evento del servidor. A partir de ahí solo se añaden acciones observadas de esa mano, una vez y en orden. Huecos en la secuencia, eventos de otra captura o posteriores al frame/tiempo evaluados invalidan el cálculo.

La configuración se borra cuando cambia la mano o empieza otra captura. La aplicación del contexto no modifica cartas, apuestas, turno, eventos ni archivo de manos. Las selecciones de Hero del panel matemático, el resumen descriptivo y el contexto preflop son explícitas; selecciona el mismo asiento si estudias el mismo jugador.

Cada resultado válido se guarda **antes de publicarlo**, en la tabla privada `preflop_results` de PostgreSQL o SQLite. Incluye snapshot de entrada, configuración, historial, modo, resultado, frame, tiempo y cursor de eventos. Una identidad derivada del contenido evita duplicar entradas idénticas y nunca sobrescribe un análisis anterior con datos posteriores. Este archivo no se mezcla con `observed_events` ni con los endpoints públicos de manos.

En memoria se mantienen solo configuración, hasta 32 acciones, último resultado y como máximo un registro pendiente de guardar. Un fallo de escritura no publica el resultado; conserva el registro pendiente y se reintenta antes de otra captura. Si ocurre procesando un frame, se interrumpe la captura. El cálculo es determinista y se ejecuta tras el guardado de eventos; las escrituras usan un hilo y el productor de vídeo conserva su cola acotada independiente.

Si cambia el estado utilizable, la evidencia o el cursor mientras se guarda un resultado, la serialización HTTP lo oculta hasta disponer de un cálculo compatible. WebSocket publica snapshots completos. Al detener la captura o perder el turno de Hero deja de mostrarse una recomendación activa.

- `TRAINING`: resultado disponible en `/live`, HTTP y WebSocket. Si se pierde la conexión, la interfaz oculta la recomendación conservada.
- `LIVE_REAL_MONEY`: `preflop.result: null` en las respuestas públicas, incluso después de detenerse. Se calcula y archiva internamente al configurar el contexto. La consulta/desbloqueo posterior corresponde a fases siguientes y no está implementada aquí.

El handshake pasa a fase 13: `strategy_available` indica disponibilidad del motor preflop en entrenamiento y sigue siendo falso en dinero real. No implica que exista una recomendación para cualquier estado.

## API e interfaz

`GET /api/preflop/defaults` entrega la tabla de ejemplo estática. `GET /api/preflop` entrega estado/configuración y el resultado filtrado por modo. `PUT /api/preflop/config` recibe:

```json
{
  "capture_id": "captura-actual",
  "state_revision": 5,
  "hand_id": "mano-actual",
  "hero_seat": 3,
  "button_seat": 6,
  "seats": [1, 2, 3, 4, 5, 6],
  "ante_total_bb": "0",
  "pot_includes_bets": true,
  "history_confirmed": true,
  "prior_actions": [],
  "rules": ["sustituir por los objetos de /api/preflop/defaults"]
}
```

El ejemplo de `rules` es un marcador explicativo, no un cuerpo válido para enviar. Cada acción monetaria requiere `{ "seat": 3, "action": "RAISE", "total_bb": "3" }`; fold/check no llevan importe. Asientos, reglas, importes y longitudes se validan; campos extra (incluido un intento de cambiar modo) devuelven 422. La UI muestra los errores y permite editar rangos/condiciones en JSON dentro de un desplegable. La configuración requiere marcar la confirmación de contexto; ante una nueva mano vuelve a solicitarla.

## Ejecutar y probar

Desde la raíz:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_preflop_video.py
```

Aplicación habitual: http://localhost:5173/live. Para comprobar recomendaciones en entrenamiento sin cambiar el modo de esa instancia:

```powershell
docker run --rm -d --name zeros-phase13-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase13-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase13-training-ui --link zeros-phase13-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

En http://localhost:5174/live reproduce `sample_data/preflop-demo.avi`. Confirma Hero 3, botón 6, seis asientos, antes cero, bote que incluye apuestas e historial `[]`. Con As Ks y 100 BB efectivos aparece Raise hasta 2,5 BB. Puedes cambiar `open_to_bb` de `open-early` a 3 y volver a confirmar el contexto. A los 20 segundos Hero sube a 300; la sugerencia desaparece al dejar de observar su turno. A los 26 segundos se muestra el flop.

Backend con Tesseract y la base PostgreSQL exclusiva de pruebas:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Después, desde `frontend/`, **ejecutar las suites de vídeo por separado**, esperando que termine cada comando:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
```

Las pruebas nuevas cubren posición, heads-up, acciones previas, sizing, antes, reglas solapadas, datos incompletos, eventos futuros/perdidos, archivo idempotente, fallo de persistencia, cambio de mano/captura y filtrado en ambos modos. El navegador utiliza vídeo, OCR, etiquetas de acción y WebSocket reales en escritorio/móvil. Bajo saturación por varios OCR simultáneos, la cola descarta frames y pueden perderse señales necesarias para reconstruir una acción; no es una prueba de rendimiento multi-mesa ni de ocho horas.

Al terminar la instancia auxiliar:

```powershell
docker stop zeros-phase13-training-ui zeros-phase13-training
```

## Archivos y siguiente fase

Validación final: **329 pruebas backend aprobadas**, con Tesseract real y PostgreSQL exclusivo de pruebas; **19 pruebas de navegador aprobadas** (15 generales y 4 de entrenamiento). Las suites de vídeo se ejecutaron por separado. Compilación TypeScript/Vite y Prettier correctos. Revisado el panel preflop en escritorio y móvil, sin desbordamiento horizontal; comprobados sizing configurable, desaparición de la sugerencia al actuar y filtrado HTTP/WebSocket en dinero real. Los servicios Compose quedaron saludables; las instancias auxiliares de entrenamiento se retiraron.

Nuevo `backend/app/strategy_engine/`: modelos, posiciones/historial, tablas ilustrativas, motor preflop, servicio y API. Integración en captura, arranque, handshake y `HandStore` (tabla privada). Pruebas en `test_preflop.py`, `test_preflop_service.py` y actualización de contratos anteriores. Demo en `backend/scripts/create_preflop_video.py`.

Nuevo `frontend/src/preflop/`, estilos, integración en `/live`, contrato de captura e indicadores de fase. Pruebas en `training-tests/preflop.spec.ts`; la suite de entrenamiento usa un solo worker porque comparte captura. README y esta guía documentan el alcance.

La fase siguiente es **14: motor postflop**, con fuerza de mano, proyectos, textura del board y contexto de rangos. Calibración de una plataforma real, detección automática de posición/antes y revisión pública de análisis archivados siguen pendientes.
