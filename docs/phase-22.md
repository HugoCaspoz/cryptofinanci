# Fase 22 — Feedback según modo

## Revisión de la fase anterior

Se revisaron la vinculación de la primera acción confirmada, las instantáneas inmutables y la recuperación de evaluaciones pendientes de la fase 21. Se conserva su corte temporal y el modelo `ev-logit-v3`: esta fase cambia el acceso y la presentación, no la fórmula de EV ni los datos usados para evaluar una decisión. Las pruebas anteriores forman parte de la validación de regresión.

## Qué cambia

TRAINING mantiene recomendaciones, tamaños, equity, pot odds y razonamiento en directo. LIVE_REAL_MONEY publica durante la mano solo observaciones: cartas, bote, stacks, eventos y estadísticas recopiladas. Los perfiles descriptivos exponen recuentos, oportunidades y tasas; los rangos adaptativos, priors y recomendaciones siguen privados.

En «Momento de revisión», dentro de `/live`, se elige antes de empezar:

- `HAND_FINISHED`: abre la revisión tras un final de mano confirmado y guardado.
- `SESSION_FINISHED`: requiere declarar explícitamente que la sesión de juego ha terminado. Es el valor predeterminado.

La preferencia inicial viene de `FEEDBACK_RELEASE`. Cambiar el selector afecta a próximas capturas hasta reiniciar el proceso. Cada captura guarda su propia política inmutable en SQLite/PostgreSQL: un cambio posterior de selector o variable de entorno nunca adelanta su desbloqueo.

Una captura equivale en esta fase a una sesión de revisión. No se agrupan varias capturas ni se añade aún un catálogo de sesiones. La página `/sessions` mantiene su estado pendiente.

## Límites de mano y sesión

Para liberar por mano se exige tanto `observed_hands.status=finished` como un evento `HAND_FINISHED` persistido. Vaciar las cartas, detener la fuente, llegar al final del archivo o perder la conexión no sustituyen ese evento. Una mano incompleta conserva esa marca.

Para liberar por sesión, la fuente debe estar detenida y su tarea terminada, sin manos activas pendientes de guardar. En «Manos → una mano → Revisión de la mano», el usuario marca «He terminado la sesión de juego de esta captura» y pulsa «Finalizar sesión y abrir revisión». El backend vacía los trabajos de instantáneas, reintenta el guardado y registra `SESSION_FINISHED` con fecha UTC y origen `user_confirmation`. El evento y el estado final se escriben en la misma transacción; repetir el cierre no duplica el evento.

El cierre explícito permite revisar también manos incompletas, sin declararlas completas ni atribuirles acciones que no se observaron. En la política por mano sirve igualmente para revisar una captura interrumpida.

Al reiniciar, las sesiones que estaban capturando pasan a `interrupted`, no a finalizadas. Los archivos anteriores sin política se migran conservadoramente a `SESSION_FINISHED` e `interrupted` cuando su modo puede verificarse. Un contexto antiguo sin modo verificable permanece bloqueado.

## Control de acceso

La política se comprueba en el backend para el listado de decisiones, su detalle, evaluación y archivo de estrategia. No basta ocultar un panel. Se valida el modo del registro y de la mano: cambiar una instancia a TRAINING no permite leer archivos de LIVE_REAL_MONEY ni viceversa.

En modo real, cualquier mano activa bloquea también el análisis histórico de otras manos. El inicio de una nueva captura bloquea la revisión incluso antes de detectar la primera mano. Entre manos, después de un final confirmado, pueden abrirse los archivos que ya cumplan su política. La autorización se vuelve a comprobar después de las lecturas asíncronas, por si ha comenzado otra mano mientras se consultaba el archivo.

Las respuestas de revisión incluyen `Cache-Control: no-store, private`. La interfaz desmonta el contenido privado al desconectarse, cambiar la captura o entrar una nueva mano. Una clave con instancia, captura y revisión impide pintar respuestas tardías de permisos antiguos. El estado y los endpoints de estrategia en directo siguen sin devolver resultados en modo real, incluso después de desbloquear un archivo.

Estos controles se basan en la captura observada y en la declaración explícita de fin de sesión. No detectan partidas fuera de esa fuente ni pueden retirar datos ya descargados por un cliente.

## Pantalla de revisión

En `/hands/:hand_id`, «Revisión de la mano» explica el bloqueo y permite cerrar la sesión cuando corresponde. Tras desbloquear, ofrece decisiones paginadas y muestra:

- Cartas, board, bote y tiempo del snapshot; aviso si el historial era parcial.
- Acción confirmada de Hero, comparación baseline/explotativa y diferencia de EV.
- Frecuencia y disponibilidad del tamaño elegido, confianza cualitativa y motivos.
- Alternativas con tamaño/EV/equity y análisis de farol cuando la evaluación los contiene.

La evaluación utiliza exclusivamente los datos congelados de la fase 20 y el cálculo de la fase 21. No incorpora cartas posteriores ni estadísticas actuales. Una diferencia negativa indica menor EV estimado frente al menú configurado, no dinero perdido ni un error categórico. Sin acción vinculada o contexto suficiente, se muestra el motivo de no poder comparar; preflop sigue sin modelo de EV. «Actualizar revisión» vuelve a cargar permisos y resultados si quedaba una evaluación pendiente.

El detalle descriptivo de la mano se vuelve a consultar al cambiar el bloqueo o la revisión, para no conservar «En curso» mientras el panel ya permite revisar una mano terminada.

## API y archivos

```text
PUT  /api/feedback/config                       {"release":"HAND_FINISHED"|"SESSION_FINISHED"}
GET  /api/feedback/hands/{hand_id}               permisos, motivo y metadatos de sesión
POST /api/feedback/sessions/{scope_id}/finish    {"session_finished":true}
GET  /api/decisions?hand_id=…                    listado, ahora sujeto a política
GET  /api/decisions/{id}                        snapshot, sujeto a política
GET  /api/decisions/{id}/evaluation              evaluación, sujeta a política
GET  /api/strategy/archive?hand_id=…             estrategia archivada, sujeta a política
```

El bloque `capture.feedback` publica preferencia para próximas capturas, política de la captura actual, revisión y bloqueo global; nunca incluye análisis. `opponents.observations` contiene solo la lista explícita de datos descriptivos.

Backend: nuevo `app/feedback/{policy,store,routes}.py`, integrado con configuración, captura, persistencia, decisiones, estrategia y estadísticas. Frontend: nuevos `FeedbackPanel` y `HandReview`, ampliación de `EvaluationReview` y presentación de estadísticas observadas. Pruebas: `backend/tests/test_feedback.py` y `frontend/review-tests/feedback.spec.ts`.

## Ejecutar y probar

Desde la raíz, con Docker Desktop iniciado:

```powershell
docker compose up --build -d --wait
```

La instancia principal está en http://localhost:5173. Compose usa LIVE_REAL_MONEY por defecto. Para entrenamiento temporal aislado:

```powershell
docker run --rm -d --name zeros-phase22-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase22-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase22-training-ui --link zeros-phase22-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

Prueba manual en modo real:

1. En `/live`, guarda la política deseada antes de iniciar la fuente.
2. Reproduce `sample_data/opponents-demo.avi` (generable con `backend/.venv/Scripts/python backend/scripts/create_opponent_video.py`). Antes de los 18 s confirma participantes 1 y 2, botón 1 e inicio sin acciones anteriores en «Modelo de rivales». En «Motor matemático» aplica Hero 1, rival 2 y bote que incluye apuestas.
3. Mientras corre la mano, comprueba que no hay recomendaciones y que el archivo devuelve 403. Las estadísticas observadas sí pueden verse.
4. Abre la mano guardada y espera al final del vídeo, de 68 segundos. Con `HAND_FINISHED` puede abrirse; con `SESSION_FINISHED` sigue bloqueada hasta marcar y confirmar el cierre.
5. Abre la decisión del flop: Hero hizo Fold. Despliega las alternativas y el análisis de farol. Recarga: el resultado sigue guardado. Una nueva captura vuelve a ocultarlo.

Backend completo con OCR y PostgreSQL exclusivo de pruebas:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`, ejecutar secuencialmente para no solapar OCR:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
npm run test:review
```

La suite de revisión usa el backend real de 5173 y comprueba las dos políticas, bloqueo activo, cierre explícito, persistencia al recargar, alternativas/faroles, escritorio/móvil y revocación al comenzar otra captura desde otro cliente. Guarda capturas en `frontend/test-results-review/`. `REVIEW_E2E_URL` permite cambiar la URL. Las pruebas escriben manos sintéticas en el archivo y restauran la preferencia `SESSION_FINISHED` al terminar.

Para retirar solo las instancias auxiliares:

```powershell
docker stop zeros-phase22-training-ui zeros-phase22-training
```

## Validación realizada

- Backend Docker con Tesseract y PostgreSQL: suite completa de **563 pruebas** en 2 min 39 s. Se añadió después el caso de reintento de cierre tras fallo de persistencia y pasó también en Docker: **564 casos verificados**. La suite focal de feedback en local pasó 15 casos y omitió el de PostgreSQL, que sí se ejecutó en Docker.
- Compilación TypeScript/Vite y `npm run format:check`: correctos.
- Navegador general: **15/15** en 3,6 min. Tras corregir la actualización del encabezado se repitió el escenario de manos: **1/1**.
- Entrenamiento: **6/6** en 3,8 min.
- Revisión: ejecución final **2/2** en 2,6 min, ambas políticas con escritorio, móvil, recarga y revocación desde otro cliente. Capturas revisadas visualmente y sin desbordamiento horizontal.

La primera ejecución de revisión pasó el caso por sesión y agotó el tiempo en el caso por mano esperando las alternativas. La política había desbloqueado correctamente, pero el OCR procesó 83 de 332 frames y no conservó la subida del rival: el snapshot quedó sin contexto estratégico y la evaluación informó que no podía comparar. No se fabricó una acción ni se debilitó el control de acceso. La prueba ahora comprueba explícitamente el estado y motivo de la evaluación antes de esperar el desplegable. La suite completa posterior pasó; la pérdida de señales por rendimiento sigue siendo una limitación del reconocimiento, no una garantía resuelta por esta fase.

Compose quedó sano en modo LIVE_REAL_MONEY, sin captura activa y con preferencia `SESSION_FINISHED`. Las instancias temporales de entrenamiento están detenidas.

## Limitaciones y siguiente fase

Se mantiene un único worker de backend y una fuente global. La política cubre el archivo de decisiones y estrategia; los archivos internos completos de rivales/preflop/equity no se exponen en modo real. No se recalculan instantáneas antiguas con información posterior. No hay búsqueda de vídeo ni frame exacto guardado, calibración de confianza estratégica o validación de cámara/mesa real.

La fase 23 prevista añade timeline de decisiones y acceso al frame exacto. No forma parte de esta entrega.
