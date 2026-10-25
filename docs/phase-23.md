# Fase 23 - Timeline de decisiones

## Revisión anterior y comportamiento

El repositorio estaba limpio y documentaba las fases 1 a 22. Se revisaron la persistencia inmutable de DecisionSnapshot, el enlace de la acción observada y los permisos de feedback. Se conserva el modelo de EV y el corte temporal del análisis.

La revisión de cada mano ofrece una línea temporal paginada, en orden de eventos, con calle, tiempo de fuente, acción evaluada, diferencia de EV baseline y disponibilidad del fotograma. Seleccionar una decisión muestra su imagen, cartas, board, bote, jugadores, stacks, apuestas y turno congelados; debajo siguen disponibles la comparación baseline/explotativa, alternativas y análisis de farol de la fase 22. Sin evaluación o EV comparable se muestra esa ausencia; las cifras no se convierten en notas categóricas de acierto.

## Persistencia y acceso

La captura solo asocia una imagen si su frame_id y timestamp coinciden exactamente con la observación del snapshot. La previsualización se actualiza antes de ceder a tareas asíncronas para evitar que un callback vea la imagen anterior. El JPEG queda en la cola de guardado junto al snapshot para reintentar sin sustituirlo por una imagen posterior.

La nueva tabla decision_frames guarda el JPEG como base64 en TEXT, compatible con SQLite y PostgreSQL. Snapshot, evento e imagen se escriben en una transacción; reintentos iguales son idempotentes y un JPEG diferente para la misma identidad se rechaza. El arranque crea la tabla sin modificar instantáneas antiguas. Se conserva solo una imagen por decisión, sin acumular todos los frames en memoria.

GET /api/decisions/{id}/frame devuelve image/jpeg; si no existe imagen devuelve 404 después de comprobar acceso. Reutiliza los permisos del archivo, comprueba de nuevo tras leer el JPEG y recibe Cache-Control: no-store, private. El inicio de otra mano bloquea también este endpoint. La interfaz descarga la imagen como blob, cancela peticiones y libera el object URL al desmontarse o revocarse la revisión. El listado usa joins paginados para traer evaluación y disponibilidad sin descargar imágenes.

## Archivos modificados

- Backend: capture_engine/engine.py, decision_engine/service.py y routes.py, hand_reconstructor/store.py, main.py.
- Frontend: feedback/HandReview.tsx y timeline.css, decisions/types.ts, App.tsx, pages/Dashboard.tsx.
- Pruebas: tests/test_decision_frames.py y test_decisions.py; frontend/tests/timeline.spec.ts, tests/app.spec.ts y playwright.config.ts; scripts/seed_timeline_review.py crea una fixture aislada.
- README.md y este documento; frontend/.prettierrc.json conserva los finales de línea locales para que format:check funcione en Windows sin reformatear el repositorio.

## Ejecutar y probar

Arranque habitual desde la raíz, con Docker Desktop iniciado:

```powershell
docker compose up --build -d --wait
```

Abrir http://localhost:5173/hands y seleccionar una mano. En modo real se exige el desbloqueo por mano o cierre explícito de sesión ya configurado. Las capturas nuevas conservarán las imágenes al detectar turnos confirmados de Hero.

Pruebas locales:

```powershell
Set-Location backend
python -m pytest -q -p no:cacheprovider
Set-Location ../frontend
npm run build
npm run format:check
```

Fixture de navegador, sin OCR ni vídeo real, con dependencias de desarrollo del backend instaladas:

```powershell
python backend/scripts/seed_timeline_review.py
```

Imprime una ruta SQLite nueva en el directorio temporal. En una terminal desde backend, usar esa ruta:

```powershell
$env:HAND_DB_PATH = '<ruta impresa>'
$env:APP_MODE = 'TRAINING'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

En otra terminal desde frontend:

```powershell
$env:API_PROXY_TARGET = 'http://127.0.0.1:8002'
npm run dev -- --port 5175
```

Desde una tercera terminal en frontend:

```powershell
$env:TIMELINE_E2E = '1'
$env:E2E_BASE_URL = 'http://127.0.0.1:5175'
$env:E2E_BROWSER_CHANNEL = 'msedge'
npx playwright test tests/timeline.spec.ts
```

La variable del navegador permite utilizar Edge instalado. Si se omite, se usa Chromium de Playwright. La prueba de timeline se omite en la suite normal salvo que TIMELINE_E2E esté activado. No ejecutar la fixture contra un archivo real: el script siempre crea una ruta temporal nueva.

## Validación realizada

- Backend completo local: 555 pruebas correctas, 11 omitidas por Tesseract o PostgreSQL no disponibles; 93,69 s.
- Suite focal de decisiones, feedback e imágenes: 34 correctas y 2 omitidas.
- Compilación TypeScript/Vite correcta.
- Navegador Edge con backend real y fixture sintética: 7/7 correctas (navegación general y reconexión incluidas). La prueba de timeline cubre anchos 1440 y 390, carga del JPEG, estado congelado, navegación a la mano y ausencia de desbordamiento horizontal. Capturas en frontend/test-results/.
- Se corrigió una carrera de la prueba de reconexión: ahora espera la conexión activa y la cierra explícitamente, sin temporizador sobre la primera conexión descartable de React en desarrollo.
- npm run format:check correcto con finales de línea locales.
- Docker estaba detenido; no se ejecutó la matriz Docker/PostgreSQL ni la suite completa de vídeo/OCR en este equipo.

## Límites y siguiente fase

El fotograma corresponde al instante observado, pero conserva el JPEG de previsualización, con calidad 80 y máximo 1280 x 720; no es una copia de los píxeles originales. No permite reproducir ni buscar en el vídeo eliminado. Los archivos anteriores o decisiones sin imagen coincidente muestran ausencia de fotograma. No se fabrican calles o decisiones no observadas.

La línea temporal se construye con las decisiones archivadas durante la captura y se consulta por mano al desbloquear la revisión. No incorpora un catálogo global de sesiones ni expone evaluaciones en directo en dinero real. La base crece con las imágenes y no hay política de retención o borrado automático.

La fase 24 prevista añadirá el explicador LLM sobre resultados estructurados del motor; no forma parte de esta entrega.


## Validación posterior (22 de octubre de 2026)

Tras iniciar Docker, se ejecutó la suite de esta entrega con Tesseract y PostgreSQL exclusivo de pruebas: **566/566 correctas, sin omisiones**, en 116,32 s. Se mantuvo la base de la aplicación separada. La fase 24 añade además una comprobación explícita de persistencia e inmutabilidad de fotogramas en PostgreSQL.
