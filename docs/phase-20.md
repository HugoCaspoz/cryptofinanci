# Fase 20 — Punto de decisión e instantánea inmutable

## Revisión de la fase 19

Se revisaron el reparto del rango, los bloqueadores, las tendencias compartidas y el archivo privado. La corrección `ev-logit-v2` sí permite que las cartas de Hero cambien el fold estimado. Se encontró un detalle adicional: el corte entre combos con la misma fuerza dependía del orden lexicográfico de sus cartas. Ahora todos los combos empatados reciben la misma proporción de continuación, respetando sus pesos (`ev-logit-v3`). Una prueba con parejas de ases y diferentes ases en Hero comprueba que el orden del rango no cambia el fold.

Los resultados de estrategia anteriores guardaban huellas de los rangos; el archivo de rivales conserva el último estado de cada captura. Eso no bastaba para reconstruir exactamente una decisión histórica. Esta fase guarda los combos ponderados completos, sin intentar reconstruir los archivos antiguos.

## Detección y corte temporal

`GameStateEngine` posee un `DecisionTracker`. La captura le entrega los datos confirmados y los modelos sincronizados hasta el evento actual. Se crea una instantánea cuando:

- La captura está en marcha, la mano está activa y el turno visual confirmado corresponde al asiento Hero configurado en el motor matemático.
- Hero no está retirado ni all-in; sus dos cartas, el board correspondiente a la calle, el bote, las ciegas y los stacks/apuestas están confirmados. La limpieza de evidencia descarta importes/cartas antiguos.
- Si existe un modelo de decisión, sus cartas, mano, apuestas y orden de turno coinciden; ningún evento, evidencia o modelo procede de un fotograma posterior.

Una oportunidad se identifica por captura, mano, Hero, calle y última acción confirmada. Refrescar un frame, cambiar ajustes o perder y recuperar brevemente la etiqueta de turno no crea otra decisión. Una nueva acción confirmada o una nueva calle permite otro punto de decisión.

Con los datos hasta el evento N se congela `DecisionSnapshot`; después se emite `HERO_DECISION_REQUIRED` como evento N+1, con su `decision_id`. El evento es descriptivo: no contiene rangos ni recomendaciones. Los consumidores lo procesan para mantener sus cursores contiguos.

## Qué conserva

El objeto es una dataclass congelada cuyo contenido es una cadena JSON canónica, identificada mediante SHA-256. Deserializarlo entrega copias independientes. No es una envoltura congelada que conserve listas mutables compartidas.

- Estado completo: identidad de captura/mano, cartas de Hero, board, bote, ciegas, stacks, apuestas, retirados, all-in y turno.
- Fotograma, tiempo de la fuente, secuencia de corte y evidencia de cada campo.
- Acciones confirmadas anteriores, con sus tiempos y secuencias; `history_complete` indica si se observó el inicio sin huecos conocidos.
- Rangos baseline y explotativos: todos los combos y sus pesos, no solo resúmenes o hashes. También los rangos manuales configurados, expandidos a combos.
- Muestras de estadísticas utilizadas por el modelo (fijadas al inicio de mano) y una copia del estado de rivales conocido en el punto de decisión.
- Configuración matemática y de estrategia, contexto de torneo, configuración/resultado preflop disponibles, versión del esquema y del modelo EV.

Si falta contexto del modelo o se empezó a observar a mitad de mano, se conservan explícitamente los desconocidos y el historial parcial. No se completan después con información posterior. Tener una instantánea no garantiza que exista suficiente información para recomendar una acción.

`DecisionSnapshot.request()` reconstruye la entrada tipada para `StrategyEngine`, sin consultar el estado vivo. La prueba de reproducción comprueba el mismo resultado antes y después de acciones, estadísticas y cartas posteriores usando la misma implementación del motor.

## Persistencia e integración

La nueva tabla `decision_snapshots` funciona en SQLite y PostgreSQL. Snapshot y evento se guardan en una transacción; los reintentos idénticos son idempotentes y una escritura diferente sobre la misma identidad se rechaza. Se conserva lo pendiente ante un fallo y el siguiente frame espera a su guardado. Iniciar otra captura también exige vaciar lo pendiente.

La estrategia de la oportunidad utiliza la entrada congelada y archiva `decision_snapshot_id`. Los ajustes posteriores se aplican a futuras decisiones. Un cálculo ya iniciado que termine después de que Hero actúe se archiva, pero no vuelve a mostrarse como consejo actual. El trabajador mantiene su cola de cálculo más reciente: bajo carga puede omitir un análisis aún no iniciado; la instantánea persiste para evaluarla posteriormente.

La ventana WebSocket contiene como máximo 20 resúmenes. Los rangos completos se leen bajo demanda:

```text
GET /api/decisions?hand_id=…&after=0&limit=20
GET /api/decisions/{decision_id}
```

El listado devuelve `items`, `has_more` y `next_after`; `limit` admite 1–100. No hay endpoint de modificación. El panel «Decisiones de Hero» muestra los resúmenes de la captura actual y permite abrir cartas, bote, stacks, acciones, muestras y JSON completo. Las capturas anteriores siguen disponibles por API con su `hand_id`.

En `TRAINING` se permite revisar instantáneas de entrenamiento. En `LIVE_REAL_MONEY` los rangos y detalles permanecen internos: listado/detalle devuelven 403 y el WebSocket no transmite resúmenes ni identidad activa. Una instancia de entrenamiento tampoco permite leer instantáneas archivadas en dinero real. El evento descriptivo puede aparecer en el historial general. La revisión posterior en dinero real corresponde a la fase 22.

## Ejecutar y probar

Desde la raíz:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_opponent_video.py
docker run --rm -d --name zeros-phase20-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase20-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase20-training-ui --link zeros-phase20-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

Compose sigue en http://localhost:5173 con el modo configurado (por defecto dinero real). La instancia auxiliar de entrenamiento está en http://localhost:5174/live y usa una base temporal independiente.

Reproduce `sample_data/opponents-demo.avi`. Antes de los 18 s confirma asientos 1 y 2, botón 1 e inicio sin acciones anteriores en «Modelo de rivales». En «Motor matemático», aplica Hero 1, rival 2 y bote que incluye apuestas. Entre los 52 y 56 s se guarda el flop A♠K♥ / J♠7♣4♦ frente a la CBet. Abre «Ver decisión · flop» y comprueba que sus datos y acciones anteriores permanecen iguales después del fold de Hero. Configura los contextos antes del turno que quieras analizar: no se rellenan instantáneas anteriores.

Backend completo, con Tesseract y una base PostgreSQL exclusiva de pruebas:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`: `npm run build`, `npm run format:check`, `npm test` y `npm run test:training`, secuencialmente. No solapar suites OCR. Retira únicamente las instancias auxiliares al terminar:

```powershell
docker stop zeros-phase20-training-ui zeros-phase20-training
```

Las nuevas pruebas cubren inmutabilidad profunda, reproducción sin datos futuros, deduplicación de turnos, historial parcial y rotación del anillo de eventos, datos incoherentes, reintentos de disco, persistencia SQLite/PostgreSQL, integración de captura/estrategia, resultados tardíos y privacidad entre modos. La prueba de navegador recorre el vídeo, abre el snapshot tras el fold, verifica rangos completos, contenido inalterado, paginación y presentación en escritorio/móvil.

Validación realizada: **516 pruebas backend aprobadas** con Tesseract y PostgreSQL (90,47 s), **15 pruebas generales de navegador aprobadas** (3,4 min) y **6 de entrenamiento aprobadas** (3,5 min), ejecutadas secuencialmente. Compilación TypeScript/Vite y Prettier correctos. Tras revisar las capturas se ajustó el margen interior del detalle; se volvió a compilar y se comprobó el panel en escritorio y móvil, sin desbordamiento horizontal. La demo guardó tres decisiones (14,4 s, 30,6 s y 52,4 s); el flop conserva sus cuatro acciones anteriores tras el fold. Compose queda saludable en fase 20 y modo dinero real, sin resultados de estrategia publicados; las instancias auxiliares se retiran al terminar.

## Archivos y límites

Nuevos: `backend/app/decision_engine/{models,tracker,service,routes}.py`, `backend/tests/test_decisions.py` y `frontend/src/decisions/`. Integraciones en GameState, eventos, captura, archivo de manos, estrategia, rutas, tipos, estilos y panel en directo. Actualizados indicadores a fase 20, prueba de navegador, prueba de bloqueadores y README.

El historial de acciones conserva hasta 512 acciones por mano; superar ese límite marca historial parcial. Las instantáneas requieren reconocer de forma coherente el turno y los datos obligatorios; un turno demasiado breve o una señal ausente puede no detectarse. `history_complete` acredita continuidad del historial observado, no demuestra que el OCR haya reconocido todas las acciones reales. No se almacena una imagen por decisión. La base no tiene aún retención automática del archivo.

El reconocimiento sigue validado con la mesa sintética Zeros. El modelo EV sigue siendo heurístico, sin calibración de población, resubidas rivales ni planes de varias calles. Reproducir un resultado exige la implementación correspondiente, además del snapshot; registrar la versión no conserva automáticamente código de motores antiguos.

La fase 21 vinculará la acción realmente tomada por Hero con esta instantánea y evaluará su diferencia de EV. Esta fase todavía no califica la decisión posterior ni desbloquea consejos en dinero real.
