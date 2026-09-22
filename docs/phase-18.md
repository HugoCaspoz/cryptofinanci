# Fase 18 — Motor de estrategia

## Qué se ha construido

`StrategyEngine` combina, en cada decisión de Hero, el `GameState` confirmado, los cálculos del motor matemático (bote, importe a igualar, equity con rangos ponderados), el modelo de rivales (historial anclado, rangos y estadísticas anteriores a la mano) y el contexto de torneo. Produce `baseline_strategy` y `exploitative_strategy` como frecuencias por acción, con sizing y EV aproximado en BB:

```json
{
  "baseline_strategy": { "summary": { "FOLD": 0.0, "CALL": 0.72, "RAISE": 0.28 } },
  "exploitative_strategy": { "summary": { "FOLD": 0.0, "CALL": 0.35, "RAISE": 0.65 } }
}
```

Las cifras son un ejemplo de formato. La visión sigue observando; el motor recibe estados y eventos, nunca imágenes. No es un solver ni una solución GTO.

## Alcance y datos necesarios

Solo se calcula cuando el turno observado es de Hero (`current_player`). Fuera de su turno el estado es `waiting` y no hay estrategia que mostrar ni archivar.

- **Hero y bote**: se usan el Hero y la convención de bote confirmados en «Motor matemático».
- **Preflop**: la primera decisión de Hero cubierta por la fase 13. La baseline es la acción de la tabla configurada, pura (100 %). La explotativa es idéntica y lo indica: una tabla determinista no ofrece un punto de partida para repartir frecuencias, y esta versión no deriva ajustes preflop de las estadísticas. Requiere aplicar «Estrategia preflop» en la mano y el mismo asiento de Hero en ambos paneles.
- **Postflop**: flop, turn y river **heads-up**, con el inicio confirmado en «Modelo de rivales» y su historial completo. El orden de ese historial debe esperar a Hero y las apuestas observadas deben coincidir con las reconstruidas. Bote, stacks, apuestas y ciegas deben estar confirmados en los últimos 2,5 s y en la misma unidad.

Multiway, all-in, decisiones preflop posteriores a la primera, huecos de eventos o un historial posterior al frame evaluado producen `unavailable` con el motivo. No hay sustitución silenciosa por rangos manuales.

## Modelo `ev-logit-v1`

> Desde la fase 19 se usa `ev-logit-v2`: el rival elige qué parte de su rango continúa sin conocer las cartas de Hero, y esas cartas modifican después el fold estimado (bloqueadores). En la fase 19 se añade también el proxy WTSD para el fold explotativo. Detalles en [fase 19](phase-19.md).

Opciones legales, en BB, con el bote total `P` (incluye las apuestas de la calle):

- Sin importe pendiente: check y bet a cada fracción del bote configurada (por defecto 33 % y 75 %).
- Con importe pendiente `C`: fold, call y raise hasta `max(multiplicador × apuesta rival, mínimo legal)` (por defecto ×3).
- Un tamaño que consume el stack pasa a `ALL_IN` y se ofrece una sola vez. Las fichas que el rival no puede cubrir se devuelven a Hero.

EV de una única decisión, medido como fichas finales de Hero menos las que añade desde ahora:

```text
R = 1 en river; 1,0 en posición y 0,9 fuera de posición en calles anteriores (supuesto)
fold   = 0
check  = R · E · P
call   = R' · E · P' − C − (F − 1) · (1 − R'·E) · C          R' = 1 si el call es all-in
bet/raise de x fichas:
  α    = x / (P + x)                                          fold que deja a un farol puro en EV 0
  EV   = f · P + (1 − f) · [R'·Ec · P'' − x − (F − 1) · (1 − R'·Ec) · x]
frecuencia(a) ∝ exp((EV(a) − EV máximo) / (dispersión · P))
```

- `P'` es el bote tras el call y `P''` el bote si el rival paga la apuesta.
- `E` es la equity de Hero contra el rango completo del rival y `Ec` contra la parte que continúa: el `1 − f` más fuerte por mano hecha actual, tras quitar combos bloqueados. Los proyectos del rival cuentan como débiles; es una simplificación.
- `F` es el factor de riesgo de torneo (1 fuera de torneo).
- No se modelan re-subidas del rival, apuestas de calles futuras ni botes laterales. El check fuera de posición no descuenta una apuesta posterior del rival.
- La dispersión (5 % del bote por defecto) reparte frecuencia entre acciones de EV parecido: una diferencia de un 5 % del bote multiplica por e ≈ 2,7 la preferencia. Acciones indiferentes se mezclan; una acción con mucha ventaja se acerca al 100 %.

Monte Carlo usa las muestras y la semilla del motor matemático (misma semilla para baseline y explotativa); river heads-up enumera exactamente. El intervalo de simulación no mide la fiabilidad del modelo.

## Baseline frente a explotativa

| Entrada | Baseline | Explotativa |
| --- | --- | --- |
| Rango del rival | Mismas acciones, repesadas con los priors genéricos de la fase 16 (`neutral_continuation_rate`), sin muestras ni prior de torneo | Rango adaptativo: estadísticas anteriores a la mano y, si existe, el prior de población del torneo |
| Fold ante una apuesta o subida de Hero | Equilibrado, `α` | CBet de flop de Hero como agresor preflop: `(aciertos + k·α) / (oportunidades + k)` con Fold to CBet del rival y `k` = fuerza del prior. Resto: `α` |
| Riesgo de torneo | Factor de la etapa | El mismo factor |

Sin observaciones ni prior de población, ambas estrategias coinciden exactamente. Con más oportunidades, la estimación se aleja de `α` según `n / (n + k)`. La baseline nunca utiliza las estadísticas del rival. Las estadísticas se congelan al inicio de la mano: las acciones de esta mano solo cambian el rango con los supuestos, no entrenan su propia muestra. El ajuste de fold se limita a Fold to CBet porque es la única estadística que mide la respuesta a una apuesta concreta; las demás respuestas mantienen la defensa equilibrada.

## Contexto de torneo

`tournament_context/stage.py` clasifica la etapa con los puestos pagados declarados y los jugadores restantes. La política es `bubble-factor-proxy-v1`: `F` es cuánto cuesta una ficha perdida respecto a una ganada, un supuesto ilustrativo sin ajustar a premios. **No es ICM.**

| Etapa | Condición | F | Satélite o premios iguales |
| --- | --- | ---: | ---: |
| `unknown` | Faltan premios o jugadores restantes | 1,0 | 1,0 |
| `early` | Más de 1,5 × pagados | 1,0 | 1,0 |
| `approaching_money` | Hasta 1,5 × pagados | 1,1 | 1,2 |
| `bubble` | Hasta pagados + max(1, 10 % de pagados) | 1,3 | 1,6 |
| `in_the_money` | Restantes ≤ pagados | 1,15 | 1,0 |

El factor penaliza las fichas que Hero arriesga en call, bet o raise; check y fold no cambian. Se puede desactivar con «Aplicar riesgo de torneo». También se informa del stack medio estimado `stack inicial × participantes / restantes`, válido solo sin recompras. El preflop no aplica el factor: la tabla no lo contempla.

## Publicación, modos y archivo

El cálculo se ejecuta en un hilo con cola de último estado: un cambio de estado, configuración o historial descarta el resultado anterior antes de publicarlo. El resultado desaparece al terminar el turno de Hero, al cambiar la mano o al detener la captura. Los datos de rivales posteriores al frame evaluado se descartan.

Cada resultado `ready` se guarda **antes de publicarse** en la tabla privada `strategy_results` de PostgreSQL o SQLite. Incluye estado confirmado, configuraciones, cursor de eventos, historial de apuestas, estadísticas congeladas, torneo, huellas SHA-256 de ambos rangos (el archivo de rivales conserva el historial para reconstruirlos), modo y resultado. Una identidad derivada del contenido evita duplicados y conserva el primer frame en que se tomó la decisión. Si la escritura falla, el resultado no se publica, el estado pasa a `storage_error` y el registro queda pendiente para reintentarlo, también antes de iniciar otra captura.

- `TRAINING`: estrategia en `/live`, HTTP y WebSocket (`capture.strategy`). Al perder la conexión se oculta.
- `LIVE_REAL_MONEY`: `result: null` en todas las respuestas públicas, también después de parar. El cálculo y el archivo continúan de forma privada; el desbloqueo tras la mano o la sesión llegará en la fase 22.

### API

- `GET /api/strategy`: estado, visibilidad, configuración y resultado filtrado por modo.
- `GET /api/strategy/defaults`: configuración inicial.
- `PUT /api/strategy/config`: preferencias de sizing. Se conservan entre capturas; no contienen hechos de la mano.

```json
{ "bet_sizes": [0.33, 0.75], "raise_multiplier": 3, "temperature": 0.05, "tournament_adjustment": true }
```

`bet_sizes`: de 1 a 4 fracciones distintas entre 0,1 y 3. `raise_multiplier`: 2–6. `temperature`: 0,01–0,5. Los campos extra, incluido un intento de cambiar el modo, devuelven 422.

- `GET /api/strategy/archive?hand_id=…`: registros de entrenamiento de una mano. En dinero real devuelve 403.

El handshake pasa a fase 18; `strategy_available` sigue siendo verdadero solo en entrenamiento.

## Ejecutar y probar

Desde la raíz del proyecto:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_opponent_video.py
docker run --rm -d --name zeros-phase18-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase18-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase18-training-ui --link zeros-phase18-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

Con Git Bash, antepón `MSYS_NO_PATHCONV=1` al primer `docker run` para que `/tmp/...` no se convierta en una ruta de Windows.

La instancia habitual (dinero real) está en http://localhost:5173/live y muestra el aviso de archivo interno. Para ver la estrategia abre http://localhost:5174/live:

1. Reproduce `sample_data/opponents-demo.avi`.
2. Antes de los 18 s, en «Modelo de rivales» deja solo los asientos 1 y 2, botón 1, y confirma el inicio.
3. En «Motor matemático» selecciona Hero 1, incluye el asiento 2, bote que incluye apuestas, y aplica.
4. Entre los 14 y 18 s Hero actúa preflop: sin «Estrategia preflop» configurada, el motor explica que su tabla es la baseline.
5. Entre los 52 y 56 s Hero afronta la CBet del asiento 2 (3 BB en un bote de 21 BB, en posición). Se muestran baseline y explotativa con Fold, Call 3,0 BB y Raise a 9,0 BB. En esta demo no hay manos anteriores: ambas estrategias coinciden y los ajustes lo explican.
6. Tras el fold de Hero la estrategia desaparece. `GET http://localhost:8001/api/strategy/archive?hand_id=…` devuelve la decisión archivada.

Backend completo con Tesseract y PostgreSQL **exclusivo de pruebas** (la base `zeros_phase9_checks` debe existir):

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Después, desde `frontend/`, sin solapar suites de vídeo:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
```

Las pruebas nuevas cubren opciones legales y all-in cubiertos, farol de EV nulo con `α`, logit, factor de riesgo, rango que continúa con bloqueos, espera fuera del turno, igualdad de baseline y explotativa sin datos, desviación creciente con la muestra, Fold to CBet limitado a su situación, prior de población solo en la explotativa, burbuja, etapas del torneo, entradas obsoletas o futuras, multiway, all-in, baseline preflop desde la tabla, rangos neutrales y estadísticas congeladas, archivo antes de publicar, duplicados, fallo de escritura y políticas HTTP/WebSocket y de archivo en ambos modos. El recorrido de entrenamiento usa vídeo, OCR, acciones y WebSocket reales en escritorio y móvil.

Para retirar las instancias auxiliares:

```powershell
docker stop zeros-phase18-training-ui zeros-phase18-training
```

## Archivos y límites

Validación realizada: **487 pruebas backend aprobadas** con Tesseract y PostgreSQL exclusivo de pruebas (en local, sin ambos, 479 aprobadas y 8 omitidas); **21 pruebas de navegador aprobadas** (15 generales y 6 de entrenamiento), ejecutadas en secuencia. Compilación TypeScript/Vite y Prettier correctas. Revisadas las capturas del panel en escritorio y móvil, sin desbordamiento horizontal. Los servicios Compose quedaron saludables en fase 18, modo `LIVE_REAL_MONEY`, captura detenida, `strategy.result: null` y archivo de estrategia con 403. Se retiraron las instancias auxiliares de entrenamiento. Persisten dos avisos de deprecación del cliente de pruebas, sin fallos.

Backend: nuevos `strategy_engine/engine.py`, `ev.py`, `strategy_service.py` y `strategy_routes.py`; `StrategyConfig` en `strategy_engine/models.py`; `opponent_model/decision.py` (entrada congelada) y rangos neutrales en `adaptive.py`; `tournament_context/stage.py`; tabla `strategy_results` en `HandStore`; integración en `capture_engine/engine.py` y `main.py`; fase 18 en salud y handshake. Pruebas en `test_strategy.py` y `test_strategy_service.py`.

Frontend: nuevo `src/strategy/` (tipos y panel), `styles/strategy.css`, integración en `/live`, contrato de captura e indicadores de fase. Recorrido `training-tests/strategy.spec.ts`.

Límites: EV de una sola decisión sin árbol de juego; realización y factores de torneo supuestos, sin calibrar; ranking del rango que continúa por mano hecha actual; ajuste de fold limitado a Fold to CBet; sin estrategia multiway, con all-in ni en decisiones preflop posteriores. Las frecuencias no expresan confianza. El reconocimiento sigue validado solo con la mesa sintética Zeros.

La fase 19 añadirá `BluffAnalyzer`: showdown value, blockers, fold equity, tendencias del rival y sizing para evaluar faroles.
