# Fase 15 — Modelo de rivales

Se incorpora un modelo incremental de estadísticas a partir de eventos confirmados. No cambia los rangos del motor matemático ni genera etiquetas estratégicas: la adaptación de rangos corresponde a la fase 16.

Se revisó la fase 14 ejecutando sus pruebas postflop y los contratos matemáticos. Las suites completas y los recorridos de navegador también comprueban las fases anteriores.

## Estadísticas y oportunidades

El modelo procesa cada acción una sola vez y actualiza sus contadores inmediatamente. Una oportunidad sin resolver no se convierte en un resultado negativo. Las definiciones generales se contrastaron con la [referencia estadística de PokerTracker](https://www.pokertracker.com/guides/PT3/general/statistical-reference-guide); los siguientes límites son decisiones explícitas de esta implementación.

| Métrica | Numerador / denominador implementado |
| --- | --- |
| VPIP | Manos con call o raise preflop / manos con preflop completo y participantes confirmados. Las ciegas no cuentan como inversión voluntaria. |
| PFR | Manos con raise preflop / la misma muestra completa. |
| 3Bet | Resubidas frente a una única subida previa / respuestas observadas con oportunidad de resubir. Incluye squeeze. |
| Fold to 3Bet | Folds del agresor inicial ante el 3Bet / sus respuestas observadas al 3Bet. No incluye cold-callers ni respuestas a 4Bet. |
| CBet flop | Bets del último agresor preflop / sus decisiones en flop cuando nadie ha apostado antes. Un check declina la oportunidad; una donk bet la elimina. |
| Fold to CBet | Folds ante la CBet / respuestas observadas a esa apuesta. No cuenta decisiones frente a una posterior subida. |
| WTSD | Jugadores que llegaron al showdown / jugadores que vieron flop en manos con desenlace confirmado. |
| AF postflop | Bets + raises / calls observados en flop, turn y river. Con cero calls se muestra «—», con los recuentos disponibles. |

VPIP/PFR se consolidan al cerrar toda la ronda preflop (última respuesta, check de BB o victoria por folds). Así una captura interrumpida después de un raise no contabiliza como pasivos a jugadores que todavía no han decidido. El BB que recibe un walk está incluido en el denominador de manos completas, con VPIP/PFR cero. Los demás contadores se resuelven tras la acción correspondiente; los contadores de acciones y manos observadas también se actualizan inmediatamente.

Una mano observada puede ser parcial. «Manos observadas» cuenta manos con una acción del jugador o participación confirmada, mientras cada porcentaje tiene su propio denominador. Sin contexto inicial solo se cuentan acciones y AF: no se inventa una oportunidad de CBet, por ejemplo, a partir de cualquier bet en flop.

## Confirmación y calidad del historial

Para métricas contextuales se confirma, antes de la primera acción, la mano actual, los asientos que recibieron cartas y el botón. Se exige preflop activo, ciegas y stacks recientes, apuestas iniciales exclusivamente de SB/BB, bote igual a SB + BB y unidades coherentes. Los asientos están numerados en sentido horario. Se rechazan contexto repetido, revisión obsoleta, acciones anteriores, antes y stacks iniciales insuficientes.

Se reconstruyen orden de acción, subidas completas, calls, checks, folds y cierre de ronda. Antes de contar una oportunidad se contrastan las apuestas resultantes de todos los asientos. Los eventos ausentes, una calle saltada, un orden imposible, cambios de identidad o un all-in suspenden las oportunidades contextuales restantes de esa mano. Los contadores de oportunidades ya resueltas se conservan; VPIP/PFR no se añaden si el preflop quedó incompleto.

AF sí admite all-in confirmado: el total frente a las apuestas de los demás permite distinguir una acción agresiva de un call, también corto. No se resuelven reaperturas por all-in ni botes laterales para los otros indicadores. Un stack cero también suspende el contexto, aunque la etiqueta visible sea raise.

Llegar al river no prueba un showdown. Cuando una mano termina tras folds confirmados, WTSD incorpora ceros para quienes vieron flop. Si finaliza después de un river con apuestas cerradas y varios jugadores, se ofrece «Confirmar showdown observado». La confirmación requiere haber visto llegar al showdown a todos los asientos indicados y solo puede contabilizarse una vez. Sin ella se excluye esa mano de WTSD. Captura detenida/EOF no equivale a mano terminada.

## Identidad y confianza

Los perfiles se separan por captura y asiento; los nombres iguales no fusionan jugadores. Un cambio de nombre confirmado abre otro perfil y suspende el contexto de la mano. Los perfiles anteriores se conservan en el archivo, mientras el panel muestra los activos. Un reemplazo de jugador con el mismo nombre visible no se puede detectar: debe iniciarse otra captura. Tampoco se fusionan automáticamente identidades entre vídeos, reinicios o mesas.

Cada proporción publica numerador, oportunidades, valor e intervalo de Wilson del 95 %. La etiqueta de confianza describe solo tamaño de muestra: ninguna con 0 oportunidades, baja con 1–29, media con 30–99 y alta desde 100. Son umbrales de presentación, no una garantía estadística de fiabilidad. El intervalo no corrige sesgo de selección por acciones perdidas, dependencia entre manos, cambios de juego ni errores de identidad/OCR. No se clasifican rivales como tight, loose, pasivos, etc.

## Persistencia, API y modos

El worker de captura consume eventos secuenciales después del archivo de manos y antes de publicar el estado. El modelo conserva solo contadores, contexto de la mano y hasta 20 showdowns pendientes; máximo de 128 perfiles por captura y 128 acciones en el historial preflop contextual. Cursor, captura, frame y tiempo impiden sumar duplicados, eventos ajenos o posteriores al estado evaluado.

La tabla privada `opponent_snapshots` guarda el último agregado por captura en SQLite/PostgreSQL, junto con su modo original, revisión y cursor. Una revisión antigua no sobrescribe otra más reciente. Ante fallo de escritura se retiene un único agregado pendiente, se oculta el resultado y se detiene la captura; se reintenta antes de iniciar otra. Una nueva captura empieza con perfiles nuevos y conserva el archivo anterior.

Endpoints:

- `GET /api/opponents`: estado actual filtrado por modo. También aparece como `capture.opponents` en HTTP y WebSocket.
- `PUT /api/opponents/context`: `capture_id`, `state_revision`, `hand_id`, `seats`, `button_seat`, `start_confirmed: true`.
- `PUT /api/opponents/showdown`: `capture_id`, `hand_id`, `showdown_observed: true`.
- `GET /api/opponents/archive/{scope_id}`: último agregado persistido de una captura de entrenamiento, solo desde entrenamiento.

Campos extra, contexto inválido y cambio de captura/revisión se rechazan. No se puede cambiar el modo por estos endpoints. `LIVE_REAL_MONEY` devuelve `analysis: null`; los perfiles se calculan y guardan internamente. Sus archivos tampoco se desbloquean consultándolos desde otra instancia en entrenamiento. No se añaden al API público de manos/eventos. La revisión posterior de dinero real sigue pendiente.

El archivo es una consulta del último acumulado, no un historial de estimaciones para cada decisión. No se usan estos acumulados posteriores para reevaluar decisiones pasadas. Tras reiniciar el backend se pueden consultar archivos de entrenamiento, pero no se retoma el contexto activo ni se confirman showdowns de la captura anterior.

## Ejecutar y probar

Desde la raíz:

```powershell
backend/.venv/Scripts/python backend/scripts/create_opponent_video.py
docker compose up --build -d --wait
```

Aplicación habitual: http://localhost:5173/live. Para probar las estadísticas visibles sin cambiar el modo de esa instancia:

```powershell
docker run --rm -d --name zeros-phase15-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase15-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase15-training-ui --link zeros-phase15-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

En http://localhost:5174/live reproduce `sample_data/opponents-demo.avi`. En «Modelo de rivales» selecciona **solo asientos 1 y 2**, botón **1**, marca la confirmación del inicio y aplica antes de los 18 s. La demo dura 68 s:

1. Asiento 1 sube a 300 a los 18 s.
2. Asiento 2 resube a 900 a los 26 s: 3Bet 1/1.
3. Asiento 1 paga a los 34 s: VPIP/PFR 1/1 en ambos y Fold to 3Bet 0/1 en asiento 1.
4. Flop a los 40 s; asiento 2 apuesta a los 48 s: CBet 1/1.
5. Asiento 1 se retira a los 56 s: Fold to CBet 1/1.
6. La mesa queda vacía a los 62 s; al confirmarse el final, WTSD 0/1 para ambos.

Los tiempos indican el cambio visual; las métricas aparecen después de confirmar OCR y etiqueta de acción. Las muestras son ilustrativas y su confianza es baja.

Backend con Tesseract y PostgreSQL **exclusivo de pruebas**, `zeros_phase9_checks` (crear esa base si aún no existe):

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Después, desde `frontend/`, ejecutar secuencialmente:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
```

Se necesitan también las demos de las fases anteriores. Ejecutar las suites de OCR por separado para evitar saturación y pérdida de señales. Las pruebas nuevas cubren oportunidades HU/multiway, squeeze, donk, subida sobre CBet, folds, showdown explícito, all-in, identidades, duplicados, huecos, eventos futuros, muestras pequeñas, archivo/reintentos y políticas HTTP/WebSocket. La demo recorre vídeo, OCR, acciones, estadísticas y persistencia, y se revisa el panel en escritorio y móvil.

Para retirar las instancias auxiliares:

```powershell
docker stop zeros-phase15-training-ui zeros-phase15-training
```

## Archivos y siguiente fase

Validación: **407 pruebas backend aprobadas** en la suite completa, con Tesseract y PostgreSQL exclusivo de pruebas. Tras reforzar la comprobación de revisión durante la escritura, se repitieron las ocho pruebas locales del servicio, incluidas las políticas de ambos modos y la regresión de cambio de estado mientras se guarda (la variante PostgreSQL ya se había ejecutado en la suite completa). **20 pruebas de navegador aprobadas**: 15 generales y 5 de entrenamiento, ejecutadas en secuencia. TypeScript/Vite y Prettier correctos. Revisadas las capturas del panel en escritorio y móvil, sin desbordamiento horizontal. La demo verificó actualización por acción y archivo de WTSD al terminar por fold. Los servicios Compose quedaron saludables en `LIVE_REAL_MONEY`, con análisis público nulo y sin errores de almacenamiento; se retiraron las instancias auxiliares de entrenamiento. Persisten dos avisos de deprecación de dependencias del cliente de pruebas, sin fallos.

Nuevo `backend/app/opponent_model/`: modelos, motor de contadores, intervalos, servicio y API. Integración en captura, `HandStore`, arranque, salud y WebSocket. Nuevos `test_opponents.py` y `test_opponent_service.py`; actualización del doble de almacenamiento en `test_hands.py` y del contrato de fase en `test_api.py`. Demo en `backend/scripts/create_opponent_video.py`.

Nuevo `frontend/src/opponents/`, estilos, contrato de captura, panel en Live e indicadores de versión. Recorrido en `training-tests/opponents.spec.ts`. README y esta guía documentan fórmulas, condiciones y comandos.

La calibración visual sigue limitada a la mesa sintética Zeros. La fase 16 añadirá adaptación de rangos a las acciones y muestras observadas, con peso dependiente de los datos disponibles.
