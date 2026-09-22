# Fase 21 — Evaluación después de actuar

Actualización de la [fase 22](phase-22.md): las evaluaciones de dinero real ya pueden consultarse cuando se cumple la política guardada de fin de mano o sesión. Los bloqueos permanentes descritos aquí corresponden al estado de la fase 21; el contrato matemático y la persistencia se mantienen.

## Revisión de la fase 20

Se revisaron la inmutabilidad, el corte temporal, el archivo SQLite/PostgreSQL y la vinculación de estrategia con `decision_snapshot_id`. Las instantáneas guardan los rangos completos y permiten reproducir los cálculos. El trabajador de estrategia en directo conserva únicamente el último trabajo pendiente: una decisión breve puede tener snapshot sin resultado calculado. La fase 21 utiliza una cola persistente independiente para que ese caso también pueda evaluarse después.

Se mantienen las pruebas de la fase 20 y sus reglas de deduplicación. La entrada congelada no se modifica al añadir una acción o evaluación. El modelo matemático sigue siendo `ev-logit-v3`; la evaluación añade su versión `decision-evaluation-v1`.

## Vinculación con la acción real

Al guardar eventos, se buscan instantáneas sin resolver de la misma captura. La primera acción confirmada posterior debe ser de Hero, en la misma mano y calle, con el mismo board y una secuencia continua desde el snapshot. Se permite que entre ambos haya actualizaciones descriptivas de OCR/turno.

Una acción intermedia de otro jugador, otra decisión, un cambio de board/mano, un hueco de eventos o el cierre de captura impiden vincular una acción posterior. El resultado queda no evaluable, con un motivo explícito. No se salta hasta el siguiente fold/call de Hero para completar artificialmente la decisión anterior.

La vinculación y los eventos se guardan en la misma transacción de SQLite/PostgreSQL. La tabla privada `decision_evaluations` tiene una entrada por snapshot y un único vínculo por acción. El trabajo conserva solo los hechos de la acción (tipo, total apostado, unidad, secuencia, tiempo, evidencia y confianza visual); **el estado posterior a la acción no se entrega al motor de estrategia**.

## Comparación y EV

`DecisionEvaluator` reconstruye la entrada mediante `DecisionSnapshot.request()` y ejecuta el motor con las cartas, rangos, estadísticas, semilla y configuración guardadas. No lee estadísticas actuales ni cartas posteriores. Si la versión del modelo EV no coincide, conserva la acción y explica que no puede evaluar con esa versión.

Se validan los importes frente a la apuesta y stack anteriores: los eventos contienen el total de la calle, no las fichas añadidas. Postflop se comprueban call, subida mínima y all-in. Una etiqueta all-in que solo paga se interpreta como call all-in. Datos incompatibles no reciben un EV.

Para baseline y explotativa se guarda:

- Acción/tamaño de referencia: opción de mayor EV entre los tamaños configurados en la instantánea.
- EV de la acción realmente tomada y diferencia frente a esa referencia.
- Frecuencia de la acción y tamaño en la estrategia original.
- Si el tamaño observado pertenecía a las opciones originales.

```text
ev_difference_bb = EV(acción real) − máximo EV(opciones configuradas)
```

Fold usa EV 0 como referencia de fichas adicionales. Una diferencia negativa indica menor EV estimado respecto a la mejor opción configurada; **no es dinero perdido realmente ni el resultado de la mano**. La comparación no usa el showdown para juzgar retrospectivamente la acción.

Si Hero utiliza otro tamaño legal, se calcula su EV por separado con el mismo modelo. No se aproxima al tamaño más cercano ni se cambia el menú/frecuencias originales. La diferencia puede ser positiva si ese tamaño supera los que estaban configurados. No se afirma haber encontrado el óptimo entre todos los tamaños posibles. Una acción mezclada puede tener menor EV puntual y seguir teniendo frecuencia en el modelo; no se etiqueta automáticamente como error.

Preflop utiliza la tabla configurada y muestra coincidencia/frecuencia, pero `actual_ev_bb` y `ev_difference_bb` quedan en `null`: la aplicación aún no dispone de un modelo EV preflop. Si faltaba contexto al congelar el turno, la evaluación conserva ese desconocimiento.

## Confianza y presentación

`confidence.value` es `null`: no se inventa una probabilidad de acierto del 74 %. Se informa confianza **limitada** cuando se puede comparar, o **insuficiente** cuando falta información. La confianza visual de la acción se archiva como `observation_confidence`, separada de la confianza estratégica. El tamaño de muestra y la continuidad del historial se conservan como contexto, sin convertirlos en una garantía de exactitud.

El panel de entrenamiento «Decisiones de Hero → Ver decisión → Después de actuar» presenta acción real, referencia baseline/explotativa, diferencia de EV redondeada a una décima y limitaciones. Diferencias inferiores a 0,05 BB se muestran como aproximadamente cero. Los números completos permanecen en el archivo para reproducir el cálculo.

La API nueva es:

```text
GET /api/decisions/{decision_id}/evaluation
```

Devuelve `{status, result}`. El estado exterior es `waiting` (sin acción/resolución), `pending` (trabajo persistido) o `complete`. El resultado puede ser `ready`, `table_only` o `unavailable` e incluye la estrategia calculada desde la instantánea. El JSON original del snapshot conserva exactamente su contrato y contenido.

WebSocket publica una revisión del archivo, no el resultado completo. Al abrir una decisión o cambiar esa revisión, el panel consulta su evaluación bajo demanda. No hay sondeo periódico. En dinero real el endpoint sigue bloqueado con 403, incluso después de terminar la mano; una instancia de entrenamiento tampoco puede leer registros de dinero real. El desbloqueo diferido corresponde a la fase 22.

## Persistencia, reintentos y recuperación

El trabajador procesa una evaluación a la vez fuera del hilo de captura. Los trabajos esperan en la base, sin una cola creciente de rangos en memoria. Un fallo de cálculo/escritura conserva el trabajo pendiente, notifica el error y permite reintentar al guardar nuevos eventos, al cerrar ordenadamente o al reiniciar. Un resultado ya guardado no puede reescribirse con otro contenido.

Al arrancar se recuperan vínculos a partir de snapshots y eventos archivados, incluidas decisiones de la fase 20. Solo pueden reproducirse entradas que conservaron esos datos y cuya versión EV coincide. Cada proceso calcula trabajos de su modo configurado; nunca publica análisis de dinero real al cambiar a entrenamiento. Los archivos de fases anteriores sin snapshots no se reconstruyen.

La búsqueda se pagina de 100 snapshots en 100 y examina hasta 512 eventos posteriores por decisión. Si no encuentra una acción antes de ese límite, declara información insuficiente. Una captura cerrada sin acción no se interpreta como fold. La persistencia sigue requiriendo un único worker de backend.

## Ejecutar y probar

Desde la raíz:

```powershell
docker compose up --build -d --wait
docker run --rm -d --name zeros-phase21-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase21-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase21-training-ui --link zeros-phase21-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

Compose está en http://localhost:5173; entrenamiento temporal en http://localhost:5174/live. Genera la demo, si falta, con `backend/.venv/Scripts/python backend/scripts/create_opponent_video.py`.

Reproduce `sample_data/opponents-demo.avi`. Antes de los 18 s confirma asientos 1 y 2, botón 1 e inicio sin acciones anteriores en «Modelo de rivales». En «Motor matemático» aplica Hero 1, rival 2 y bote que incluye apuestas. Hero toma dos decisiones preflop y afronta una CBet en el flop entre los 52 y 56 s. Después de su fold, abre la decisión de flop: verás la acción Fold y la comparación contra el EV de las opciones de aquel instante. Recargar la página conserva la evaluación. Sin configurar la tabla preflop antes de esos turnos, sus acciones quedan guardadas, pero la comparación preflop no estará disponible.

Backend completo con Tesseract y PostgreSQL exclusivo de pruebas:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`: `npm run build`, `npm run format:check`, `npm test` y `npm run test:training`, secuencialmente para evitar solapar OCR. Para retirar las instancias auxiliares:

```powershell
docker stop zeros-phase21-training-ui zeros-phase21-training
```

Pruebas nuevas: Fold/Check/Call/Bet/Raise/all-in, call all-in corto, tamaños fuera del menú, importes incoherentes, secuencias ambiguas, preflop sin EV inventado, falta de modelo y cambio de versión, persistencia/reinicio/idempotencia, reintento tras fallo, PostgreSQL y privacidad HTTP/WebSocket. El navegador comprueba que el fold de la demo se compara con la estrategia previa y que la evaluación sobrevive a recargar.

Validación realizada: **548 pruebas backend aprobadas** con Tesseract y PostgreSQL (119 s), **15 pruebas generales de navegador aprobadas** (3,9 min) y **6 de entrenamiento aprobadas** (3,6 min), ejecutadas secuencialmente. TypeScript/Vite y Prettier correctos. Revisadas las capturas del panel en escritorio y móvil, sin desbordamiento horizontal.

En esta ejecución, la demo congeló el flop a los 52,6 s y confirmó el fold de Hero a los 57,0 s. Baseline y explotativa recomendaron Call (sin muestra previa coinciden); el fold obtuvo EV 0 frente a aproximadamente +5,6 BB del call, por lo que se mostró una diferencia de −5,6 BB y confianza limitada. Son cifras del modelo heurístico para esa entrada, no una valoración calibrada del juego real. Las frecuencias de la interfaz se redondean a porcentajes enteros; el archivo conserva los valores completos.

Compose queda saludable en fase 21, modo dinero real, captura detenida, `strategy.result: null`, instantáneas internas y sin errores de evaluación. Las instancias auxiliares de entrenamiento se retiran tras la validación.

## Archivos y siguiente fase

Nuevos: `backend/app/decision_engine/evaluation.py`, `evaluation_service.py`, `backend/tests/test_decision_evaluation.py` y `frontend/src/decisions/EvaluationReview.tsx`. Integración en captura, almacenamiento, rutas de decisiones, estrategia, tipos, panel y estilos. Actualizados indicadores de fase, prueba de API, prueba de navegador, README y documentación.

Continúan las limitaciones del reconocimiento sintético y del modelo EV heurístico: postflop heads-up, sin modelar resubidas rivales ni planes de varias calles, sin calibración de población ni garantía de precisión. La fase 21 no añade cámara ni evaluación de sesiones completas.

La fase 22 implementará el feedback según modo y el desbloqueo de la revisión en dinero real al terminar la mano o sesión, según configuración.
