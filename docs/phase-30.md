# Fase 30 — Dashboard de sesiones

`/sessions` consulta las sesiones persistidas del modo actual, en páginas de 20. `/session/:scope_id` muestra el resumen al terminar la captura. Desde el TOP 10 se abre la mano con `?decision=:id`, su snapshot, fotograma y explicación local u OpenAI según la configuración existente. Una decisión enlazada puede estar fuera de la primera página de la línea temporal; se consulta por identificador y se verifica que pertenezca a la mano abierta.

## Métricas y límites

- **Manos observadas:** registros de la captura, incluyendo las incompletas, que se muestran por separado.
- **Manos jugadas:** manos con identidad única de Hero y dos cartas conocidas en el archivo. Se muestra la cobertura de identidad; las manos sin identificar no se cuentan como cero. Cambios contradictorios de asiento excluyen esa mano. Los archivos antiguos pueden recuperar la identidad desde los snapshots, pero no se inventa la identidad de manos sin datos.
- **VPIP/PFR:** proporción de manos con inversión voluntaria/subida preflop, entre rondas completas y legales con inicio confirmado. Las ciegas no son inversión voluntaria.
- **3-bet:** subidas de Hero al responder a una única subida previa, dividido por oportunidades observadas. Cada mano aporta como máximo una oportunidad. All-in, huecos, correcciones o interrupciones antes del cierre invalidan esa ronda. Un denominador vacío se presenta como no disponible. La API incluye muestra, intervalo de Wilson y nivel de confianza por tamaño de muestra.
- **EV estimada no capturada:** suma de `max(0, -baseline.ev_difference_bb)` para evaluaciones archivadas listas con diferencia finita. No ejecuta un solver, no utiliza el board posterior ni suma resultados monetarios. Las decisiones sin evaluación comparable se excluyen y se muestra su número. Si no hay ninguna, la EV es desconocida, no cero.
- **TOP 10 costosas y menor diferencia:** rankings entre las decisiones comparables del modelo base. Una decisión con menor diferencia no implica una ganancia real ni una recomendación universal. Los historiales parciales se etiquetan.
- **Faroles no tomados:** acción pasiva con arrepentimiento positivo y un candidato a farol/semifarol archivado con ganancia de EV positiva. **Agresiones costosas con equity baja:** acción agresiva con diferencia negativa y equity al recibir call menor del 50%. Esta última clasificación es una aproximación; no identifica la intención de farolear.
- **Fugas:** agrupa costes por oportunidad de farol, agresión de baja equity o calle y acción; muestra las cinco categorías con mayor suma.
- **Rivales:** perfiles duraderos de la captura y modo, paginados de 20 en 20. Sus identidades se conservan aunque hayan salido de la caché activa.

El contexto preflop confirmado se conserva en `hand_preflop_contexts`, sin sustituirlo posteriormente. `hand_heroes` conserva asignaciones observadas al guardar las manos y si se conocieron las cartas. No modifica snapshots ni evaluaciones anteriores.

## Acceso y memoria

En entrenamiento se permite revisar una captura detenida o interrumpida, marcada como parcial. En dinero real el resumen completo exige una sesión finalizada explícitamente, incluso si su política permite revisar manos individuales antes. El usuario debe detener la captura y marcar la confirmación de fin de juego; el dashboard usa el mismo endpoint de confirmación existente. Nunca se confirma automáticamente al terminar un vídeo.

Se comprueba el acceso antes y después del cálculo. Una mano activa en dinero real vuelve a bloquear los resúmenes. Las respuestas llevan `Cache-Control: no-store, private`; la UI invalida los datos por identidad de servidor, captura, revisiones y permisos, aborta respuestas antiguas y oculta el contenido al desconectarse o bloquearse.

Las consultas recorren decisiones, manos y eventos en páginas de 100. Solo se conservan diez filas por ranking, cinco fugas, hasta 128 acciones para reconstruir una ronda y veinte perfiles visibles. No se cargan JPEG ni todas las manos de la sesión en memoria. El tiempo del cálculo crece con el archivo; no se ha medido el dashboard sobre ocho horas de OCR real.

## Archivos principales y ejecución

Backend: `session_dashboard.py`, `session_statistics.py`, rutas API, persistencia de manos/perfiles y contexto de captura. Frontend: `pages/Sessions.tsx`, `pages/sessions.css`, `pages/Dashboard.tsx` y enlace de decisiones en `feedback/HandReview.tsx`. Versión: `0.30.0`.

```powershell
docker compose up --build -d --wait
```

Abre http://localhost:5173/sessions. Si aún no hay capturas, el archivo estará vacío. Los datos sintéticos de validación se generan en contenedores separados, sin añadir manos a la base principal.

Validación: batería completa de backend con SQLite y base PostgreSQL exclusiva; pruebas específicas de cobertura preflop, EV inválida, rankings entre páginas, aislamiento de modos, revocación y persistencia sin snapshots. Navegador Edge: navegación, sesiones, fotogramas, explicación local, revocación por WebSocket, vistas de 1440/390 px y regresiones de captura. Resultado final: **654 pruebas de backend**, **14 de navegador** y **1 de estrategia en entrenamiento**, todas correctas. Incluye 23 pruebas nuevas de sesiones y comprobación de persistencia en PostgreSQL. Compilación, Prettier y `git diff --check` correctos. Los tres servicios Compose quedan sanos, en modo dinero real y sin captura activa. Informe: [phase30-validation.json](validation/phase30-validation.json).

Esta es la última fase de `app.md`. El siguiente trabajo de producto es calibrar y validar una plataforma real: las pruebas sintéticas no certifican precisión de OCR ni rentabilidad de la estrategia.
