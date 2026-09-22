# Fase 12 — Motor matemático

`PokerEngine.analyze(GameState, PokerConfig)` produce métricas y equity sin leer vídeo ni generar acciones recomendadas. La captura entrega snapshots inmutables al servicio de cálculo después de guardar los eventos. La fase 13 incorporará la estrategia preflop.

## Cálculos y supuestos

- **Bote total**: requiere configurar si la cifra observada incluye las apuestas de la calle. Si no las incluye, suma las apuestas de todos los asientos, también los retirados. Si falta alguna lectura o las unidades difieren, no inventa el total.
- **Stack efectivo actual**: mínimo entre las fichas restantes de Hero y cada rival. En multiway también devuelve un agregado `min(hero, max(rivales))`, identificado como tal. No reconstruye el stack al comienzo del flop.
- **SPR actual**: stack efectivo / bote total, solo con bote positivo y unidades coincidentes.
- **Importe a igualar**: máximo de apuestas de los participantes menos la apuesta ya realizada por Hero, limitado a su stack restante.
- **Pot odds**: bote total antes del call / importe adicional del call. **Equity mínima teórica**: call / (bote + call). Con bote 300, apuesta de Hero 50 y apuesta rival 150, call = 100, odds = 3:1 y umbral = 25 %. No es una recomendación de call ni una estimación de EV.
- Con cero pendiente, bote cero/desconocido, unidades incompatibles, call que no cubre la apuesta o indicios de botes laterales, se omiten los umbrales que no pueden justificarse. También se rechaza como total un bote menor que la suma de apuestas conocidas en su unidad. No hay conversión automática a BB. Importes exactos con `Decimal`; ratios y probabilidades numéricos.

Referencias de las definiciones: [pot odds](https://www.pokerstars.com/poker/learn/lesson/pot-odds/) y [SPR](https://www.pokerstars.com/poker/learn/lesson/introduction-to-stack-to-pot-ratio-spr/). Los supuestos sobre apuestas futuras, rake y acceso a botes laterales limitan su interpretación.

## Rangos y equity

Configura manualmente Hero y **todos los rivales participantes**. La detección actual no distingue de forma completa asientos vacíos de jugadores activos. La configuración es un supuesto explícito, persiste entre manos de la misma captura y debe revisarse en cada mano; una captura nueva la borra. Los folds confirmados excluyen automáticamente a ese rival.

Rangos admitidos: `random`, pares `AA`, clases `AK`, `AKs`, `AKo` y combos `AsKh`, separados por comas. Peso relativo opcional **por combo**, por ejemplo `AA:0.5,KK,AKs`. Todos los combos de una clase reciben el mismo peso. No se admiten `+`, intervalos, cartas repetidas, clases solapadas, pesos no finitos, cero o negativos. `random` es un prior uniforme explícito, no una estimación del comportamiento del jugador.

Se retiran los combos bloqueados por Hero y board. Monte Carlo sortea los rangos independientemente y rechaza la **asignación completa** si dos rivales comparten una carta; después completa el board sin reemplazo. Así evita el sesgo de renormalizar secuencialmente los rangos de los rivales. Se cuentan victorias y empates; la equity es la fracción media ganada, `1 / número de ganadores` en un empate.

Predeterminado: 1.000 muestras, semilla 42. API: 100–5.000 muestras, hasta cinco rivales y como máximo 20 intentos por muestra solicitada. Si los rangos no permiten completar el muestreo dentro del límite, se devuelve un aviso y **ninguna equity parcial**. Mismos datos, rangos y semilla producen el mismo resultado. River heads-up enumera todos los combos compatibles y pondera el resultado exactamente.

El evaluador compara la mejor mano de cinco entre siete cartas, incluyendo rueda A–5, dobles tríos, tres parejas, kickers y empates jugando solo el board. El intervalo del 95 % de Monte Carlo usa una cota de Hoeffding para la media de fracciones entre 0 y 1; es conservador. Solo expresa incertidumbre de muestreo, no confianza en el OCR ni en los rangos. En el river exacto el intervalo coincide con el valor calculado.

## Integración, vigencia y modos

`PokerService` descarta del cálculo valores retenidos cuyo estado ya no sea `confirmed`, evidencia ausente o confirmaciones de más de 2,5 segundos de tiempo de fuente. El board vacío debe estar confirmado. Las lecturas originales permanecen en la interfaz descriptiva. Las regiones pueden haberse confirmado en momentos distintos: esta fase no resuelve toda incoherencia temporal del OCR.

Un trabajo en segundo plano y **un único snapshot pendiente**, sustituible por otro más reciente. No bloquea la cola de vídeo esperando Monte Carlo. Solo recalcula si cambia el estado utilizable o la configuración. El resultado incluye identidad de captura lógica (`scope_id`), mano, frame y tiempo de fuente utilizados. Al cambiar la entrada se retira inmediatamente el resultado previo; un resultado terminado de una generación anterior se descarta. La parada del servidor espera el trabajo acotado en curso. No se conservan simulaciones ni historiales ilimitados en RAM.

El snapshot HTTP y WebSocket incluye `poker.config`, `status`, `visibility` y `analysis`:

- `TRAINING`: resultados visibles en el panel **Motor matemático** de `/live`.
- `LIVE_REAL_MONEY`: cálculo interno, pero `analysis: null` en **todas** las respuestas públicas del motor y la captura. Este filtrado se aplica en el backend, también tras detener la fuente. No hay desbloqueo ni archivo duradero de análisis todavía; solo se conserva el último resultado interno. Manos y eventos siguen archivándose como antes.

No hay recomendaciones, tamaños de apuesta, EV ni cambios de modo desde el navegador. `strategy_available` continúa en `false` en ambos modos. Hero para cálculos también determina el stack mostrado en **Mano actual**; sin configurar el motor sigue disponible la selección visual local anterior.

## API

`GET /api/poker` devuelve el mismo snapshot filtrado que la captura. `PUT /api/poker/config` configura la captura actual y programa el cálculo:

```json
{
  "capture_id": "identificador-devuelto-al-iniciar-la-fuente",
  "hero_seat": 2,
  "opponents": [{"seat": 1, "range": "QQ,KK,AKs"}],
  "pot_includes_bets": true,
  "samples": 1000,
  "seed": 42
}
```

Una captura sustituida devuelve 409. Configuración inválida, asientos repetidos, Hero entre los rivales o campos extra devuelven 422 sin sustituir la configuración anterior. `pot_includes_bets: null` conserva la convención como desconocida.

## Ejecutar y probar

```powershell
docker compose up --build -d --wait
```

Abre http://localhost:5173/live. Con el modo predeterminado se configura el motor y se observa su estado interno; los resultados no se publican. Para una instancia de entrenamiento independiente, con las imágenes ya construidas:

```powershell
docker run --rm -d --name zeros-phase12-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase12-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase12-training-ui --link zeros-phase12-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

Abre http://localhost:5174/live y reproduce `sample_data/ocr-demo.avi`. En el motor selecciona Hero 2, rival 1 con `QQ,KK,AKs` y bote que incluye apuestas. Esta es una hipótesis de entrenamiento de dos participantes sobre la demo. Al cambiar las lecturas desde el segundo 8: bote 1500, call 500, stack efectivo 12000, SPR 8, pot odds 3:1 y umbral 25 %. La equity depende del rango configurado. Los importes ocultos de los segundos 5–7 no se usan como actuales.

Backend desde la raíz (PostgreSQL utiliza la base exclusiva ya descrita en la fase 9):

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Frontend desde `frontend/`, con las dos instancias en marcha y los vídeos demo generados:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
```

`TRAINING_E2E_URL` permite otra dirección para las pruebas del motor. Las pruebas de entrenamiento usan OCR y WebSocket reales, configuran rangos desde el formulario, contrastan métricas, cambian a un rango bloqueado y comprueban escritorio/móvil. Las pruebas backend cubren categorías de manos, ponderación, empates multiway, muestreo sin sesgo secuencial, importes exactos, valores desconocidos, botes laterales, vigencia, invalidación al cambiar captura/configuración y filtrado HTTP/WebSocket en ambos modos.

Al terminar la comprobación independiente:

```powershell
docker stop zeros-phase12-training-ui zeros-phase12-training
```

## Archivos y límites

Validación final: **287 pruebas backend aprobadas** en Docker, con Tesseract real y PostgreSQL exclusivo de pruebas. **17 pruebas de navegador aprobadas**: 15 de regresión y 2 de entrenamiento con OCR/WebSocket reales. Compilación TypeScript/Vite y Prettier correctos. Revisadas las capturas del panel en escritorio y móvil, sin desbordamiento horizontal. Verificados el frontend v0.12 y el filtrado de la instancia final en dinero real. Los tres servicios Compose quedaron saludables; se retiraron las dos instancias temporales de entrenamiento.

Nuevo `backend/app/poker_engine/`: evaluador, rangos, configuración, métricas, simulador, motor, servicio y rutas. Integración en `capture_engine/engine.py`, `main.py`, API de salud y handshake (fase 12). Nuevos tests `test_poker.py` y `test_poker_service.py`.

Nuevo `frontend/src/poker/` y `styles/poker.css`; integración en `/live`, contratos de captura y Hero. Indicadores de fase actualizados. Pruebas aisladas en `training-tests/` con configuración Playwright propia. README e instrucciones actualizados.

No hay rangos aprendidos por posición/acciones, estimación de fold equity, rake, resolución de botes laterales, modelo ICM, EV ni estrategia. Los resultados son condicionales a los participantes/rangos elegidos y a la calidad del estado observado. No se ha validado una sala real ni una sesión de ocho horas.

La siguiente fase es **13: motor preflop**, con rangos según posición, stacks y acciones, y `StrategyResult` separado de los cálculos matemáticos.
