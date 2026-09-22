# Fase 14 — Motor postflop

El motor matemático analiza flop, turn y river a partir de `GameState` confirmado. La visión sigue observando; no elige acciones. Se revisaron y ejecutaron las pruebas del motor preflop de la fase 13 antes de validar la integración completa.

## Qué calcula

- Mejor mano de cinco cartas: categoría, desempate, set/trips, top/middle/bottom pair, overpair/underpair, pareja del board y si Hero juega exclusivamente el board.
- Proyectos de color y escalera: abierta, gutshot, doble gutshot y una punta exterior (por ejemplo A234). Enumera cartas de finalización y une las listas sin contar dos veces una carta que completa ambos proyectos. Distingue backdoors de flop y elimina proyectos en river o hacia categorías inferiores a la mano formada. Una escalera que solo completa el board no se atribuye a Hero.
- Textura: emparejamiento, distribución de palos, carta alta y máximo de rangos dentro de una ventana de escalera, incluida A2345. La etiqueta descriptiva es «coordinado» con tres rangos en una ventana o tres cartas del mismo palo, «semicoordinado» con dos del mismo palo y «seco» en los demás casos. Emparejamiento se informa por separado.
- Equity y SPR reutilizan los cálculos de fase 12, con hasta cinco rivales para la equity de la mano concreta.
- Posición relativa entre participantes configurados, ordenados en sentido horario desde el asiento posterior al botón. Incluye heads-up y posiciones intermedias multiway; excluye folds confirmados. No atribuye posición de acción cuando detecta all-in. Depende de confirmar participantes y botón.
- Tamaños observados: contribución total de cada asiento en la calle dividida por el bote al inicio de esa calle. El bote inicial se obtiene restando **todas** las contribuciones al bote total. Datos ausentes, unidades mezcladas o denominador no positivo impiden el cálculo. No se presenta ese cociente como tamaño de la última apuesta.

Las cartas de finalización no son «outs limpios»: no garantizan ganar, no descuentan cartas ocultas y no incluyen todas las mejoras posibles, como pasar de pareja a full. El backdoor se señala sin estimar probabilidad. Las definiciones de proyectos se contrastaron con [PokerStars: calcular outs](https://www.pokerstars.com/poker/learn/lesson/calculating-outs/).

## Rangos y nuts

La comparación requiere un rango manual de Hero y **un rival**. No infiere rangos del historial; eso corresponde a fases posteriores. Usa los rangos completos bloqueados por el board actual, sin fijar las cartas concretas observadas de Hero. Es un estudio distinto de la equity de la mano concreta.

La equity de rangos usa repartos conjuntos ponderados: extrae ambos rangos de manera independiente y rechaza todo reparto con colisiones. Después completa el board uniformemente. Semilla reproducible, 100–5000 muestras, máximo de 20 intentos por muestra y error si no completa la cantidad solicitada. En river enumera exactamente las parejas de combos cuando el producto de tamaños es como máximo 25.000; los casos mayores usan simulación. No devuelve estimaciones parciales tras agotar intentos.

La ventaja de rango solo se atribuye si el intervalo conservador del 95 % queda completamente por encima o debajo del 50 %. El intervalo de Hoeffding describe muestreo, no la fiabilidad del rango o del OCR. Se reutilizan hasta 32 resultados/boards mediante cachés acotadas para no repetir comparaciones cuando solo cambian importes.

La **ventaja por densidad de nuts es un indicador limitado**: se enumeran todas las manos de dos cartas compatibles con el board, se identifica el mejor valor actual y se mide la fracción ponderada de combos que alcanza ese valor en cada rango por separado. No condiciona esa densidad a las cartas del otro rango, no mide una distribución completa de equity ni predice quién tendrá las nuts en river. Si las nuts están en el board, ambos rangos tienen densidad 100 %. Es una definición más estrecha que la ventaja en la parte alta de la distribución descrita por [GTO Wizard](https://blog.gtowizard.com/what-is-equity-in-poker/), y se etiqueta expresamente como indicador, sin afirmar una solución GTO.

## Contexto, API y publicación

`PUT /api/poker/config` admite el nuevo campo opcional:

```json
{
  "postflop_context": {
    "hand_id": "identificador de la mano actual",
    "hero_range": "JJ,AA,AK",
    "button_seat": 2
  }
}
```

Este fragmento se añade a la configuración matemática existente junto con `capture_id`, Hero, rivales y convención del bote. `hero_range` y `button_seat` pueden ser nulos. Campos extra, rangos inválidos y asientos fuera de límites se rechazan. Un contexto de otra mano devuelve 409. Al cambiar de mano dejan de aplicarse rango y botón anteriores; la interfaz vuelve a desmarcar la confirmación. Los demás rangos/participantes matemáticos requieren revisión manual, como en fase 12.

El resultado añade `analysis.postflop` con `hand_strength`, `draws`, `board_texture`, `position`, `bet_sizing`, `range_comparison` y advertencias. Los resultados descriptivos siguen disponibles aunque los rangos sean incompatibles. Un board o Hero sin confirmar impiden todo análisis postflop. El worker conserva solo el estado más reciente y descarta resultados de generaciones anteriores.

`TRAINING` publica el análisis por HTTP y WebSocket y muestra el panel dentro de «Motor matemático». Al perder conexión se oculta el análisis. `LIVE_REAL_MONEY` mantiene `analysis: null` en todas las respuestas públicas, incluso después de detener la captura. No hay endpoint alternativo de resultados. La revisión posterior y los snapshots de decisiones siguen pendientes; esta fase no añade archivo privado postflop, recomendaciones de acción, sizing recomendado ni solver.

## Ejecutar y probar

Desde la raíz:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_ocr_video.py
```

Aplicación habitual: http://localhost:5173/live. Para comprobar el panel en una instancia de entrenamiento separada:

```powershell
docker run --rm -d --name zeros-phase14-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase14-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase14-training-ui --link zeros-phase14-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

En http://localhost:5174/live reproduce `sample_data/ocr-demo.avi`. Selecciona Hero 2, rival 1 con `QQ,KK,AKs`, bote que incluye apuestas, rango de Hero `JJ,AA,AK` y botón 2. Marca la confirmación postflop y aplica. As Jh sobre Js 7c 4d muestra pareja/top pair y Hero último en actuar, además del estudio de rangos. El importe a igualar, equity y SPR cambian con las lecturas monetarias. La demo dura 16 segundos; puedes repetirla para configurar el panel desde el principio.

Pruebas backend con OCR real y PostgreSQL exclusivo de pruebas (crear previamente `zeros_phase9_checks` si no existe; nunca usar la base de la aplicación):

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`, una vez finalizado backend, ejecutar secuencialmente:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
```

Las demos anteriores deben existir, incluida `preflop-demo.avi` (ver fase 13). No ejecutar suites de OCR simultáneas: pueden saturar el equipo y hacer que la cola descarte señales.

Pruebas nuevas: categorías y procedencia de mano, wheel, gutshots, 15 finalizaciones únicas de proyecto combinado, backdoors, board-only, texturas, comparación ponderada, colisiones conjuntas, nuts compartidas, contexto por mano, multiway, sizing incompleto y lecturas caducadas. Se amplían los contratos HTTP/WebSocket de ambos modos y el recorrido de entrenamiento con OCR real en escritorio/móvil.

Para retirar las instancias auxiliares:

```powershell
docker stop zeros-phase14-training-ui zeros-phase14-training
```

## Archivos y límites

Validación final: **372 pruebas backend aprobadas**, con Tesseract real y PostgreSQL exclusivo de pruebas; **19 pruebas de navegador aprobadas** (15 generales y 4 de entrenamiento). Compilación TypeScript/Vite y Prettier correctos. Se revisaron capturas del panel postflop en escritorio y móvil, sin desbordamiento horizontal. Se verificaron las políticas HTTP/WebSocket de ambos modos y se corrigió el orden de cartas en los combos de `random`, con una regresión que conserva los 1.176 combos posibles en flop. La suite final incluye los casos de importes inválidos y all-in. Persisten dos avisos de deprecación de las dependencias del cliente de pruebas; no hubo pruebas fallidas. Compose quedó saludable y se retiraron las instancias auxiliares.

Backend: nuevos `poker_engine/postflop.py` y `range_analysis.py`; ampliaciones en modelos, motor y rutas matemáticas; versión/fase en arranque, salud y WebSocket. Pruebas en `test_postflop.py`, `test_poker_service.py` y `test_api.py`.

Frontend: nuevo `poker/PostflopAnalysis.tsx`; configuración, tipos y estilos matemáticos; indicadores de fase y texto en Live; ampliación de `training-tests/poker.spec.ts`. Documentación en README y esta guía.

Reconocimiento validado con la mesa sintética Zeros; falta calibración y validación de plataformas reales. La comparación de rangos es heads-up, el botón es manual y el sizing describe contribuciones. La fase 15 añadirá estadísticas de rivales después de cada acción, con oportunidades observadas y confianza de la muestra.
