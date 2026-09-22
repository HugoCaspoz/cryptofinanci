# Fase 9 — Límites de mano y archivo duradero

Se detectan automáticamente inicios y finales a partir de observaciones confirmadas, se emiten `HAND_STARTED` y `HAND_FINISHED` y se conservan las manos con sus eventos. La detección de acciones sigue pendiente de la fase 10.

## Señales y estados

El nuevo `HandLifecycle` consume el estado estabilizado y su evidencia, no imágenes. Usa las tres confirmaciones de cartas y el filtro OCR existentes.

- Al observar cartas confirmadas de Hero con board confirmado vacío, o un board confirmado, abre una mano con identificador único. Si no se observó antes una mesa vacía sostenida, marca `partial_start=true`: puede haberse conectado a mitad de una mano.
- Tras haber visto un board, la retirada confirmada de Hero y board durante al menos 1,2 segundos y tres observaciones adicionales permite cerrar la mano. Una región ilegible o pendiente no cuenta como vacía y rompe la espera.
- En preflop, la desaparición de Hero no basta para finalizar: puede haberse retirado mientras otros jugadores continúan. Se requiere además reinicio confirmado del bote, o posteriormente cartas distintas tras un intervalo vacío sostenido.
- Cartas nuevas de Hero y board vacío pueden indicar un nuevo reparto si también se observó retirada del board, un intervalo vacío sostenido o reinicio de bote junto con cambio de stack. Las señales de reinicio de board, bote y stack caducan a los ocho segundos de fuente.
- Un cambio aislado de cartas, de bote o de stack no separa manos. Una corrección del board tampoco. No se infieren check, bet, call, raise, fold ni all-in.

Cuando hay nuevo reparto, el flujo contiene `HAND_FINISHED` de la mano anterior **antes** de `HAND_STARTED` de la nueva, aunque ambos se confirmen en el mismo frame. El cierre conserva el último estado observado antes de la retirada de cartas. Las observaciones posteriores al cierre no se asignan a la mano anterior.

Cada nueva mano posterior a la primera reinicia los filtros de bote, stacks y apuestas. Se requieren nuevas lecturas para esos importes; no se arrastran como confirmados desde la mano anterior ni se inventan ceros. Nombres y ciegas siguen sus filtros continuos.

`GameState` añade `hand_status`: `unidentified`, `active`, `finished` o `incomplete`; el estado del evento de cierre es `finished`. Entre manos, el estado observado vuelve a `unidentified` y `hand_id=null`. `observation_state.hands` expone el estado activo, contadores de inicios/finales y las últimas 20 manos terminadas de la captura.

## Captura incompleta y fallos

EOF, detener captura o un error no prueban que la mano terminó. Si estaba activa, se guarda como **incompleta**, se emite `CAPTURE_ENDED` y no se fabrica `HAND_FINISHED`. El tiempo de este evento es el del último frame observado, no una estimación del final real de la mano.

Si el proceso se reinicia, los registros que quedaron activos se marcan incompletos con motivo `backend_restart`. No se reconstruyen eventos que no llegaron a confirmarse ni a guardarse. Se mantiene el requisito de **un único worker de backend**; la recuperación de activos no está diseñada para varios procesos analizando a la vez.

Un error al guardar detiene el procesamiento de esa captura, muestra `hand_storage.error` y conserva el lote pendiente en memoria. Al intentar iniciar otra fuente se reintenta ese lote antes de reemplazar el estado. Si continúa el fallo, no se inicia la nueva fuente. Si el proceso se pierde antes de poder reintentar, solo sobrevive lo que ya estaba confirmado en la base de datos.

## Persistencia

Compose conecta el backend con **PostgreSQL** usando las credenciales locales existentes y espera a que la base esté saludable. Se añade `psycopg[binary]==3.3.6`, instalado según la [documentación oficial de Psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html). En desarrollo local sin `DATABASE_URL` se usa SQLite en `data/hands.sqlite3`, configurable con `HAND_DB_PATH`.

Dos tablas conservan la información:

- `observed_hands`: identidad, captura, número local de mano, estado, inicio parcial, tiempos/frame confirmatorios, motivo de cierre y último estado relevante, además de fuente y modo.
- `observed_events`: eventos completos identificados por captura y secuencia; los eventos de una mano se pueden consultar por páginas.

Cada lote de eventos y cambios de manos se escribe en una transacción. Los reintentos son idempotentes. El cierre y la apertura que coinciden en un frame se guardan juntos. La escritura se ejecuta en un hilo y se espera antes de publicar el resultado del frame: el event loop sigue atendiendo peticiones y el productor de vídeo mantiene su cola limitada.

El historial en memoria continúa limitado a 40 eventos, 20 cierres recientes y el lote de la observación en curso. El archivo duradero conserva los eventos anteriores a ese límite; los datos crecen en disco, no en una lista de RAM. No hay política automática de borrado ni copias de seguridad en esta fase.

La base PostgreSQL usa el volumen de Compose existente; `docker compose down` lo conserva. La base local SQLite está excluida del repositorio y de los contextos Docker. Los tests locales usan bases SQLite temporales aisladas.

## API e interfaz

- `GET /api/hands?limit=20&offset=0&scope_id=…`: listado paginado; filtro de captura opcional. El máximo es 100 registros.
- `GET /api/hands/{hand_id}?after=0&limit=100`: estado de la mano y página de eventos con `has_more` y `next_after`. No carga todo un historial largo en memoria.
- 404 para una mano inexistente, 422 para paginación inválida y 503 si no puede leerse el archivo.
- `GET /api/capture` añade seguimiento de manos y estado del almacenamiento.
- `GET /health` indica el tipo de persistencia configurado. La disponibilidad de una escritura se confirma cuando se ejecuta; no se hace una consulta SQL por cada healthcheck.

En `/live`, **Manos observadas** muestra contadores, inicio parcial, cierre pendiente y errores de guardado. El enlace lleva a las manos de esa captura. `/hands` muestra el archivo completo, con actualización manual y paginación; `/hands/:id` muestra la mano y sus eventos. Los estados incompletos aparecen explícitamente. No se ofrecen recomendaciones en ninguno de los dos modos.

La sección `/sessions` sigue reservada para agrupación y análisis de sesiones, todavía no implementados; las manos guardadas se consultan en su propia sección.

## Ejecutar y probar

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_hand_video.py
```

Abre http://localhost:5173/live y reproduce `sample_data/hands-demo.avi` (34 segundos):

1. Mesa vacía hasta el segundo 4.
2. Primera mano A♠ J♥ y flop J♠ 7♣ 4♦. La ocultación negra del segundo 13 no termina la mano.
3. Retirada de cartas desde el segundo 18; el cierre se confirma durante el intervalo vacío.
4. Segunda mano Q♥ Q♠ desde el segundo 24 y flop A♥ 9♦ 2♣ desde el 29.
5. El archivo termina con la segunda mano abierta: se guarda como incompleta.
6. Abre las manos guardadas, recarga o reinicia el backend: la primera terminada y la segunda incompleta siguen disponibles.

Backend:

```powershell
docker compose build backend
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm zeros-backend-tests
```

La prueba PostgreSQL opcional necesita una base **exclusiva para pruebas**, indicada por `HAND_TEST_POSTGRES`; no debe apuntar a la base de la aplicación. En esta fase se utiliza `zeros_phase9_checks` en el servicio `db`, y el contenedor de pruebas se conecta a la red `zeros_default`. El resto de pruebas no escribe en PostgreSQL de producción.

Con las credenciales locales predeterminadas y esa base de pruebas creada:

```powershell
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`, con los cinco vídeos de prueba generados y sin captura activa:

```powershell
npm run build
npm run format:check
npm test
```

### Validación realizada

- Backend en Docker con Tesseract real y PostgreSQL de pruebas: **200 pruebas aprobadas**.
- Navegador Chromium contra Compose: **13 pruebas aprobadas**, incluidas separación de dos manos, ocultación, EOF incompleto, recarga, OCR, cartas, captura de pestaña y navegación móvil sin desbordamiento.
- Compilación TypeScript/Vite y comprobación Prettier correctas. Revisadas las capturas del archivo en escritorio y del detalle en móvil; el menú móvil distribuye sus cuatro enlaces en dos filas.
- Reinicio real del backend: el archivo mantuvo sus seis manos de prueba. Se compararon íntegramente los detalles y eventos de las dos manos de la demo antes y después: sin cambios, con estados terminada e incompleta.
- Frontend, backend y PostgreSQL quedaron saludables en Compose.

## Archivos

- Nuevo `backend/app/hand_reconstructor/`: ciclo de mano, archivo transaccional y rutas.
- Integración en GameState, CaptureEngine y publicación asíncrona del pipeline; nuevo evento de captura incompleta.
- Configuración de PostgreSQL/SQLite, Compose, dependencia Psycopg y versión/fase 9.
- Nuevo generador `backend/scripts/create_hand_video.py`, pruebas de límites/persistencia/recuperación/PostgreSQL y aislamiento de bases de test.
- Nuevo `frontend/src/hands/`, estilos, navegación, panel en directo y páginas de archivo.
- Pruebas de navegador para dos manos, ocultación, cierre, EOF incompleto y consulta tras recargar. Ajustes de pruebas anteriores por los nuevos eventos de mano.

## Límites y siguiente fase

Son heurísticas para el layout y los vídeos sintéticos actuales, todavía sin validación en una sala real. No se detecta el botón del dealer ni el jugador activo. Sin suficientes señales de reinicio, el motor conserva la mano en curso: puede omitir una separación, especialmente si se repiten cartas o no se observa el intervalo entre manos. No se garantiza identificar cada límite con una cámara o animaciones no calibradas.

Se prueba memoria acotada con 150 manos sintéticas; no se ha validado una sesión real de ocho horas. El archivo conserva observaciones y límites, no una hand history completa de apuestas. La fase 10 combinará stacks, apuestas y señales visuales para reconstruir acciones.
