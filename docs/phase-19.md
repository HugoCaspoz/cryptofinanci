# Fase 19 — Detección de faroles

Nota posterior: la revisión de la [fase 20](phase-20.md) distribuye proporcionalmente los combos empatados en fuerza al cortar el rango (`ev-logit-v3`). Elimina un desempate artificial por orden de cartas; las cifras de la demo descritas aquí corresponden a la validación histórica con v2.

## Revisión de la fase 18

Antes de empezar se revisó el motor de estrategia. El modelo `ev-logit-v1` elegía la parte del rango rival que continúa **después** de quitar las cartas de Hero, con lo que la frecuencia de fold quedaba fija en el valor supuesto: los bloqueadores nunca cambiaban la fold equity. `ev-logit-v2` corrige el orden:

1. El rival decide sobre todo su rango (no conoce las cartas de Hero): continúa con el `1 − f` más fuerte por mano hecha actual y se retira con el resto.
2. Las cartas de Hero eliminan combos de ambas partes.
3. El fold estimado es el peso retirado que sobrevive dividido por el peso total que sobrevive.

Cada opción agresiva publica ahora `range_fold_probability` (decisión del rival sobre su rango: `α` en la baseline, o la estimación con estadísticas) y `fold_probability` (condicionada a las cartas de Hero). Sin observaciones, baseline y explotativa siguen coincidiendo.

## Qué se ha construido

`BluffAnalyzer` (`strategy_engine/bluff.py`) se ejecuta dentro de `StrategyEngine` en cada decisión postflop heads-up de Hero y se publica como `result.bluff`. Reutiliza las filas de EV de la fase 18, así que sus cifras coinciden con las estrategias mostradas. Devuelve:

| Campo | Significado |
| --- | --- |
| `bluff_candidate` | La mejor apuesta o subida no es de valor y rinde más que la mejor alternativa pasiva (check, call o fold). |
| `recommended_sizing` | La apuesta o subida de mayor EV entre los tamaños configurados. |
| `estimated_fold_frequency` | Fold del rival con ese tamaño, condicionado a las cartas de Hero. |
| `blockers` / `unblockers` | Efecto de cada carta de Hero sobre el rango que continúa y el que se retira. |
| `reason` | Explicación en una frase. |
| `baseline_strategy` / `exploit_strategy` | El mismo análisis con los supuestos de cada estrategia. |

Los campos de nivel superior repiten el análisis explotativo, que incorpora todo lo observado; sin datos coincide con la baseline.

## Evaluación

- **Showdown value**: equity contra el rango rival completo (baseline): alto ≥ 50 %, medio ≥ 25 %, bajo. Incluye la mano hecha. Si un farol no compensa y la mano conserva equity, el motivo lo dice.
- **Clasificación de la opción agresiva**: `value` si la equity contra el rango que continúa es ≥ 50 %; `semi_bluff` si es menor, no es river y Hero tiene cartas de finalización de proyecto; `bluff` en los demás casos. Las apuestas de valor nunca se etiquetan como farol.
- **Fold equity**: fold necesario `α = x / (P + x)` (deja un farol puro en EV 0), fold del rango según la estrategia y fold estimado tras bloqueadores. `fold_shift_from_blockers` = estimado − rango.
- **Blockers**: cartas de Hero que retiran una fracción mayor del rango que continúa que del que se retira. **Unblockers**: cartas que retiran del rango que se retira menos que una carta aleatoria no vista (`2 / cartas no vistas`), es decir, dejan intactos los folds. Una carta puede estar en ambas listas; es el caso ideal para farolear. Ejemplo: 5♥6♥ en J♠7♣4♦2♥9♠ bloquea los proyectos fallidos que se retiran y no ofrece unblockers.
- **Ventaja de rango y de nuts**: compara los rangos **percibidos** de Hero y del rival (los del modelo adaptativo, construidos solo con las acciones, sin las cartas reales de Hero) con la comparación de la fase 14. Es contexto de credibilidad: no entra en el EV, para no contar dos veces la misma información.
- **Textura, proyectos y SPR**: textura del board, cartas de finalización, backdoors y SPR del motor matemático. La ocupación del stack (`commitment`) indica qué parte del stack arriesga el tamaño recomendado.
- **Tendencias del rival**: Fold to CBet, WTSD, CBet, Fold to 3Bet y agresividad postflop, con muestra, tasa suavizada y peso de los datos. Las tasas se suavizan igual que en la fase 16.
- **Sizing**: cada tamaño tiene su propio `α`, su rango que continúa, su equity cuando paga y su EV; se recomienda el de mayor EV.
- **Frecuencia de farol**: la parte que la estrategia de la fase 18 reparte a apuestas y subidas cuando son farol (cero si son de valor). Con acciones casi indiferentes el logit las mezcla, aunque no sean candidatas.

### Tendencias y fold explotativo

El modelo de fold es único para estrategia y faroles (`strategy_engine/tendencies.py`):

```text
CBet de flop de Hero como agresor preflop:
  f = (fold_to_cbet_aciertos + k·α) / (oportunidades + k)
Resto de apuestas y subidas postflop (proxy WTSD, sin calibrar):
  wtsd = (aciertos + k·0,28) / (oportunidades + k)
  f = α · (1 − wtsd) / (1 − 0,28)        limitado a [0,01; 0,99]
Sin oportunidades: f = α (explotativa = baseline)
```

Un rival que llega al showdown más de lo supuesto se retira menos y viceversa. La tasa 0,28 es un supuesto, no una medida de población. Tampoco se basa en etiquetas: el ajuste es proporcional a la estadística y a su muestra.

## Publicación y modos

El análisis forma parte del resultado de estrategia: se archiva en privado antes de publicarse (tabla `strategy_results`) y hereda sus reglas. En `TRAINING` aparece en «Motor de estrategia → Análisis de farol»; en `LIVE_REAL_MONEY` el resultado completo sigue siendo `null` en HTTP y WebSocket y el archivo devuelve 403. Preflop no se analizan faroles (la baseline es la tabla); fuera del turno de Hero, con datos incompletos o sin apuesta/subida legal no hay análisis.

El handshake y la salud pasan a fase 19. No hay endpoints nuevos.

## Ejecutar y probar

Desde la raíz del proyecto:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_opponent_video.py
docker run --rm -d --name zeros-phase19-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase19-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase19-training-ui --link zeros-phase19-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

Con Git Bash, antepón `MSYS_NO_PATHCONV=1` al primer `docker run`.

En http://localhost:5174/live reproduce `sample_data/opponents-demo.avi`, confirma en «Modelo de rivales» los asientos 1 y 2 con botón 1 antes de los 18 s, y en «Motor matemático» Hero 1, rival 2 y bote que incluye apuestas. Entre los 52 y 56 s Hero (A♠K♥) afronta la CBet en J♠7♣4♦. «Análisis de farol» muestra la subida a 9 BB como farol que no compensa frente al call (unos 1,3–1,6 BB menos según el frame) y conserva valor de showdown (36 %). A y K no son bloqueadores aquí: retiran sobre todo combos AK/AQ/KQ que se retirarían, así que el fold estimado baja del 30 % necesario al 28 %. También aparecen rangos percibidos (ventaja del rival) y tendencias sin muestra; baseline y explotativa coinciden. La decisión archivada incluye `result.bluff`.

Backend completo con Tesseract y PostgreSQL exclusivo de pruebas:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`, secuencialmente: `npm run build`, `npm run format:check`, `npm test`, `npm run test:training`. Para retirar las instancias auxiliares: `docker stop zeros-phase19-training-ui zeros-phase19-training`.

Pruebas nuevas en `test_bluff.py`: bloqueadores y cartas que dejan intactos los folds, valor nunca etiquetado como farol, abandono con valor de showdown, Fold to CBet que convierte un abandono en farol explotativo, semifarol en flop y no en river, proxy WTSD solo con muestra, desplazamiento del fold por bloqueadores, rangos percibidos, ausencia de apuesta legal y preflop sin consejo. `test_strategy.py` cubre el nuevo reparto del rango con cartas de Hero. La prueba de entrenamiento comprueba el análisis en vídeo real y en el archivo.

## Archivos y límites

Validación realizada: **497 pruebas backend aprobadas** con Tesseract y PostgreSQL exclusivo de pruebas (en local, 489 aprobadas y 8 omitidas); **21 pruebas de navegador aprobadas** (15 generales y 6 de entrenamiento), en secuencia. Una primera ejecución de la suite de entrenamiento tardó 25 minutos y agotó el tiempo de `poker.spec.ts` (escritorio); repetida aislada y después completa (6/6 en 3,4 min) pasó sin cambios en ese flujo, por lo que se atribuye a carga del equipo. Compilación TypeScript/Vite y Prettier correctas; revisadas capturas de escritorio y móvil sin desbordamiento. Compose saludable en fase 19, modo `LIVE_REAL_MONEY`, captura detenida y `strategy.result: null`. Se corrigió además la etiqueta de fase del menú lateral, que seguía en la 17.

Backend: nuevos `strategy_engine/bluff.py` y `tendencies.py`; `ev.py` pasa a `ev-logit-v2` (`split`); integración en `engine.py`; `compare_ranges` acepta un rango de Hero ponderado; fase 19 en salud, handshake y versión. Pruebas en `test_bluff.py` y actualización de `test_strategy.py`, `test_strategy_service.py` y `test_api.py`.

Frontend: nuevo `src/strategy/BluffAnalysis.tsx`, tipos y estilos del análisis, indicadores de fase y ampliación de `training-tests/strategy.spec.ts`.

Límites: el orden por mano hecha actual trata los proyectos del rival como débiles; no hay re-subidas del rival ni planes de varias calles (un farol de turn no considera el river); el proxy WTSD y los factores de realización no están calibrados; la ventaja de rango se informa pero no entra en el EV; sin multiway, all-in ni faroles preflop. El reconocimiento sigue validado solo con la mesa sintética Zeros.

La fase 20 detectará el punto de decisión de Hero (`HERO_DECISION_REQUIRED`) y congelará un `DecisionSnapshot` inmutable con cartas, board, bote, stacks, rangos, acciones y estadísticas disponibles en ese instante.
