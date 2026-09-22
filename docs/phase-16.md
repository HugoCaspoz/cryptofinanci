# Fase 16 — Modelo adaptativo de rivales

## Qué se ha construido

`OpponentModel` mantiene un rango ponderado por participante desde un inicio de mano confirmado. Cada call, bet o raise legal repondera únicamente el rango de su actor. Las estadísticas anteriores se congelan antes de la primera acción: esta mano no entrena su propia estimación. El resto del contador de estadísticas sigue actualizándose como en la fase 15, para futuras manos.

Los checks conservan los pesos (no se supone debilidad); los folds excluyen al participante. Cada nueva calle elimina los combos bloqueados por el board y renormaliza. Las cartas reales de Hero no se usan para inferir el rango del rival; el motor de equity sí las bloquea al repartir. Un prior sin combos compatibles queda vacío, nunca se amplía automáticamente a `random`.

La interfaz muestra combos compatibles, combos efectivos, ocho clases con mayor masa y la estadística usada por la última acción, con tasa suavizada, oportunidades previas y peso de los datos. El número efectivo `1 / sum(p²)` describe concentración, no confianza. El porcentaje de una clase es la suma de sus combos: una clase offsuit tiene más combos que una pareja.

## Supuestos y fórmulas de la versión action-likelihood-v1

Se pueden configurar antes de la primera acción `range_priors` (un rango por participante, por defecto `random`) y `prior_strength` entre 1 y 1000 (por defecto 30). El endpoint existente `PUT /api/opponents/context` valida y persiste ambos. No se permite corregir el contexto de la misma mano utilizando datos posteriores.

Para una estadística con `hits` éxitos y `n` oportunidades anteriores:

```text
tasa_suavizada = (hits + fuerza * tasa_prior) / (n + fuerza)
peso_datos = n / (n + fuerza)
```

Con cero oportunidades la tasa es exactamente el prior. Con 30 oportunidades y fuerza 30, datos y prior pesan lo mismo. Se usa el denominador de cada estadística, no el total de manos observado. Por ejemplo, cien manos sin oportunidad de 3Bet no equivalen a cien oportunidades de 3Bet.

Los priors de tasas son supuestos de esta versión, no frecuencias de una población validada:

| Estadística o proxy | Prior | Uso |
| --- | ---: | --- |
| VPIP | 0.28 | Calls preflop generales; proxy de continuación |
| PFR | 0.18 | Primera subida preflop |
| 3Bet | 0.07 | Subida ante una única subida previa |
| Fold to 3Bet | 0.55 | Complemento para continuar pagando como agresor inicial |
| CBet | 0.55 | Apuesta del último agresor preflop en flop sin apuesta previa |
| Fold to CBet | 0.45 | Complemento para continuar ante la CBet original |
| Acciones agresivas / (agresivas + calls) | 0.50 | Proxy postflop restante; no es AF ni una probabilidad calibrada de acción |
| Proxy de cuarta subida o posterior | 0.04 | Sin muestra estadística propia |

WTSD no entra en los pesos: no describe una acción concreta. El histórico de AF puede incluir acciones confirmadas de manos parciales, igual que en fase 15. Las tasas anteriores guían la concentración, no se presentan como probabilidades exactas de la acción actual.

La fuerza `q` de cada combo es un percentil, con empates a mitad de grupo, entre todos los combos compatibles con el board. Preflop se ordena con `rango_alto + rango_bajo + 16*pareja + 3*suited - max(0, separación-1)`. Postflop se ordena por el evaluador de la mejor mano actual de cinco cartas; no por equity futura ni por outs. El percentil no utiliza cartas de calles futuras.

```text
r = tasa_suavizada, o su complemento para continuación ante 3Bet/CBet
likelihood = exp((1 + 3*(1-r)) * (q-1))
si CALL: likelihood *= 1 - 0.65*q
nuevo_peso = peso_anterior * likelihood
normalizar todos los pesos a suma 1
```

Los pesos positivos permiten faroles y trampas; no se corta un porcentaje rígido de manos. Se trata de una heurística versionada, sin entrenamiento ni calibración contra datos reales. No es un solver ni una estrategia GTO. El modelo no incorpora tamaño de apuesta, posición, proyectos postflop, stack relativo, rake o torneo. La fuerza del prior modifica la influencia de las muestras, no valida los supuestos.

## Integración y publicación

`PokerConfig.range_source` acepta `manual` (predeterminado, compatible con fases anteriores) o `adaptive`. En adaptativo, los rangos manuales de los rivales se ignoran. Deben coincidir Hero y todos los participantes activos con el contexto confirmado. El cálculo recibe una copia inmutable de los pesos, captura, mano, board y evento; la cola descarta resultados anteriores si cambian pesos o estado y rechaza entradas de un fotograma o instante futuro.

Los mismos pesos entran en la equity de la mano (también multiway) y en la comparación heads-up con un rango manual de Hero. En river heads-up se enumera la equity exacta; en los demás casos se mantiene la simulación acotada y reproducible. Su intervalo solo describe el error de Monte Carlo, nunca la incertidumbre del modelo de rival.

Una captura distinta, mano terminada, historial incompleto, cambio de identidad, all-in no soportado o rango vacío impide reutilizar esos pesos para el cálculo. No hay fallback silencioso a rangos manuales. Los resúmenes inválidos se marcan como suspendidos. La persistencia usa el archivo privado existente en SQLite/PostgreSQL: versión, priors, estadísticas históricas, board, historial de acciones con evidencia y resúmenes. Se conserva el último contexto por captura; todavía no es el archivo de `DecisionSnapshot` de la fase 20 ni permite reanudar una mano tras reiniciar.

`TRAINING` publica rangos, estadísticas y equity. `LIVE_REAL_MONEY` mantiene `analysis: null` tanto por HTTP como por WebSocket; el archivo de dinero real sigue reservado. La fase 16 no añade consejos de acción postflop.

## Ejecutar y probar

Desde la raíz:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_opponent_video.py
docker run --rm -d --name zeros-phase16-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase16-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase16-training-ui --link zeros-phase16-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

La aplicación habitual está en http://localhost:5173/live. Para ver cálculos de entrenamiento usa http://localhost:5174/live:

1. Reproduce `sample_data/opponents-demo.avi`.
2. Antes de los 18 s, confirma en «Modelo de rivales» solo los asientos 1 y 2, botón 1 e inicio sin acciones previas. Los priors opcionales están en «Supuestos de los rangos adaptativos».
3. En «Motor matemático», selecciona origen adaptativo, Hero 1, rival 2 y bote que incluye apuestas; pulsa «Aplicar cálculo».
4. La subida del asiento 1 a los 18 s y la 3Bet del asiento 2 a los 26 s cambian sus pesos. En la primera mano el peso estadístico es 0 %, aunque se observa 3Bet 1/1 en el contador: esa nueva oportunidad solo influirá en las manos siguientes.
5. El call a los 34 s vuelve a ajustar al asiento 1. El flop a los 40 s elimina los combos bloqueados (de 1326 a 1176 para un prior completo); la CBet a los 48 s ajusta al asiento 2. El fold de Hero a los 56 s detiene su equity. El final de mano queda archivado.

Estas son señales de un vídeo sintético calibrado; aún no validan una grabación de una sala real ni una cámara.

Backend completo con PostgreSQL **exclusivo de pruebas** (la base `zeros_phase9_checks` debe existir):

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Después, desde `frontend/`, sin ejecutar suites de vídeo a la vez:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
```

Las pruebas nuevas verifican influencia creciente de las oportunidades, prior vacío, pesos positivos y normalizados, bloqueos, ausencia de información futura, aislamiento de snapshots, checks, folds, all-in, cambios de identidad y huecos; incluyen un caso exacto con equity 25 % y comprobación de que la comparación de rangos usa los mismos pesos. Se amplían las comprobaciones de archivo, HTTP y WebSocket. El recorrido de entrenamiento usa vídeo, OCR y acciones reales del pipeline para verificar la actualización y el archivo de rangos en escritorio y móvil.

Para retirar las instancias auxiliares:

```powershell
docker stop zeros-phase16-training-ui zeros-phase16-training
```

## Archivos y siguiente fase

Validación realizada: **425 pruebas backend aprobadas**, con Tesseract y PostgreSQL exclusivo de pruebas; **20 pruebas de navegador aprobadas** (15 generales y 5 de entrenamiento), ejecutadas en secuencia. TypeScript/Vite y Prettier correctos. Revisadas las capturas del panel de rivales en escritorio y móvil, sin desbordamiento horizontal. El recorrido de vídeo confirmó los pesos adaptativos, su uso para equity y el archivo al terminar. Persisten dos avisos de deprecación en dependencias del cliente de pruebas, sin fallos.

Los servicios Compose quedaron saludables en fase 16, modo `LIVE_REAL_MONEY`, captura detenida, sin error de captura ni de almacenamiento y con los análisis públicos ocultos. Se retiraron los dos contenedores auxiliares de entrenamiento; los comandos de esta guía permiten volver a iniciarlos.

Nuevo `backend/app/opponent_model/adaptive.py`; extensión de modelos, motor y ruta de contexto. Integración en `capture_engine/engine.py` y en modelos, servicio, engine, equity y comparación de rangos de `poker_engine`. Nuevo `backend/tests/test_adaptive_ranges.py`; ampliación de pruebas de servicio y contrato de fase.

Nuevo `frontend/src/opponents/AdaptiveRangeView.tsx`; ampliación de paneles, tipos, estilos y recorrido `training-tests/opponents.spec.ts`. Actualizados indicadores a fase 16 / v0.16, README y esta guía.

La fase 17 añadirá configuración del torneo: buy-in, moneda, tipo, stack inicial, participantes y premios, con priors iniciales cuya influencia disminuya conforme existan observaciones.
