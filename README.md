# Zeros · Poker Lab

Base de una aplicación de análisis de Texas Hold’em a partir de vídeo en directo. La especificación completa y el orden de desarrollo están en [app.md](app.md). **Implementadas: fases 1 a 22. La vista en directo reúne vídeo, mano actual y eventos actualizados por WebSocket. El motor matemático calcula métricas, equity y análisis postflop; el motor preflop aplica tablas configurables con contexto confirmado. El modelo de rivales adapta rangos a las acciones y estadísticas. El contexto de torneo añade buy-in, formato, participantes y premios, con un prior de población opcional que pierde peso frente a los datos. El motor de estrategia combina todo ello en cada decisión de Hero y produce frecuencias baseline y explotativas; el analizador de faroles evalúa fold equity, bloqueadores, valor de showdown y tendencias del rival. Cada turno confirmado de Hero conserva una instantánea inmutable con los datos conocidos entonces y se compara después con la acción tomada. Los resultados se muestran en entrenamiento y se desbloquean en dinero real al terminar la mano o la sesión, según la política guardada. Validado con vídeos sintéticos; falta calibrar y validar una plataforma real.**

En `/live` puedes reproducir un archivo como stream o compartir una pantalla/ventana mediante el navegador. La previsualización muestra frames recibidos por el backend. El detector reconoce cartas mediante referencias visuales y confirma cambios entre frames. El OCR lee nombres, stacks, apuestas, bote y ciegas, conservando los valores confirmados durante lecturas dudosas. No se garantiza una reconstrucción completa cuando faltan señales; la estrategia preflop exige datos confirmados y coherentes.

## Arranque con Docker

Requisitos: Docker Desktop iniciado con contenedores Linux y Docker Compose.

Desde la raíz del proyecto:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

- Aplicación: http://localhost:5173
- API y documentación: http://localhost:8000/docs
- Salud de la API: http://localhost:8000/health
- WebSocket, a través del frontend: ws://localhost:5173/ws/live

Compose levanta frontend (Nginx), backend (FastAPI) y PostgreSQL con volumen persistente. El backend guarda manos y eventos en PostgreSQL. La agrupación y el análisis de sesiones siguen pendientes. El endpoint de salud indica el tipo de persistencia configurado; los errores de escritura se notifican en la captura.

```powershell
docker compose logs --tail 100
docker compose down
```

`down` conserva el volumen de PostgreSQL. Los puertos HTTP están publicados solo en la interfaz local. Las credenciales predeterminadas son de desarrollo.

## Capturar vídeo

1. Abre http://localhost:5173/live en Chrome o Edge.
2. Selecciona los FPS de captura: 1, 2, **5 por defecto**, 10 o 15.
3. Para un archivo, selecciónalo y pulsa **Reproducir archivo**. Se admiten MP4, MOV, MKV, AVI y WebM hasta 256 MB, siempre que su códec sea compatible con el decodificador.
4. Para el escritorio, pulsa **Compartir pantalla o ventana** y elige la superficie en el selector del navegador. No se captura audio.
5. Comprueba la imagen, el contador de frames y el tiempo de fuente. Pulsa **Detener captura** antes de cambiar a otra fuente.

Los archivos se suben primero a almacenamiento temporal y se leen a su ritmo original; no se analizan completos antes de mostrar imágenes. Se eliminan del servidor al terminar, detenerse o fallar la captura. El original de tu ordenador se conserva. Al finalizar un vídeo se mantiene su último frame como referencia.

La captura de pantalla funciona también con el backend de Docker: el navegador recoge las imágenes seleccionadas y las envía al servidor. El permiso lo solicita el propio navegador cada vez; requiere un contexto seguro (localhost o HTTPS). La captura continúa al navegar dentro de la aplicación; al cerrar o recargar la pestaña que comparte la pantalla se detiene. Si se pierde el envío sin un cierre limpio, el backend detecta 15 segundos de inactividad. Un vídeo de archivo continúa en el servidor aunque cierres la pestaña.

Se mantiene una única fuente global por instancia del backend. Ejecuta Uvicorn con un solo worker. Las pestañas comparten el estado y pueden detener la fuente actual.

Vídeo de prueba de 12 segundos, con tiempo y contador visibles:

```powershell
backend/.venv/Scripts/python backend/scripts/create_sample_video.py
```

Después selecciona `sample_data/capture-demo.avi` en la aplicación. El script necesita las dependencias del backend instaladas.

## Pipeline y depuración

La captura y el procesamiento se ejecutan de forma independiente, con un worker para cada etapa. Una cola limitada a **2 frames por defecto** conserva trabajo pendiente; si se llena, descarta el más antiguo. El procesador toma siempre el más reciente y descarta el resto de frames pendientes desactualizados.

En `/live`, abre **Depuración del pipeline**, debajo de la previsualización. Muestra FPS reales de captura y procesamiento, ocupación y capacidad de cola, frames descartados, contadores y latencias. Los FPS usan una ventana móvil de 5 segundos, requieren un segundo de muestra y pasan a cero al terminar. Los contadores y últimas latencias permanecen visibles hasta la siguiente captura.

`FRAME_QUEUE_SIZE` permite configurar entre 1 y 8 frames. Para Docker, edita `.env` y ejecuta `docker compose up -d`. Para ejecución local, establece `$env:FRAME_QUEUE_SIZE = '2'` en la terminal del backend antes del arranque. No hace falta cambiarlo para utilizar la aplicación.

La latencia se mide desde que el frame está disponible en el backend hasta que se publica su resultado; no incluye captura original del navegador, transmisión de red ni renderizado de la UI. `VisionEngine` observa cartas dentro del layout y `GameStateEngine` confirma esas lecturas sin reconstruir aún manos completas. Consulta [fase 3](docs/phase-3.md) para el contrato y las métricas del pipeline.

## Mano actual y eventos en directo

En `/live`, el resumen junto al vídeo muestra Hero, board, bote, stack, calle y turno observado. Selecciona manualmente el **Asiento de Hero** para asociar su stack; la aplicación no deduce ese asiento. En móvil, el resumen se sitúa debajo del vídeo. Las lecturas y controles de calibración se mantienen después del historial principal.

El estado y la ventana de eventos llegan mediante una suscripción WebSocket, sin sondeo HTTP de `/api/capture`. Al perder la conexión se conserva el último estado con un aviso; al reconectar se recibe un snapshot actual, sin duplicar eventos ni aceptar revisiones atrasadas. La previsualización JPEG y las órdenes de captura siguen usando HTTP. El historial muestra tiempos de fuente `HH:MM:SS`; «Incluir cambios de estado» permite ver las revisiones técnicas además de cartas y acciones. Contrato, límites y pruebas en [fase 11](docs/phase-11.md).

## Configurar la mesa

En `/live`, **Configuración de regiones** permite mostrar 29 rectángulos sobre la imagen: cartas de Hero, board, bote, botón, ciegas y cuatro zonas por cada uno de los seis jugadores. Selecciona una región y ajusta X, Y, ancho y alto; el overlay muestra el borrador inmediatamente. Puedes ocultar sus etiquetas para comprobar los límites.

El único layout inicial es **Zeros demo, 1920 × 1080, seis asientos**. Es una plantilla sintética, no una plataforma de póker ya calibrada. Para ver el ejemplo:

```powershell
backend/.venv/Scripts/python backend/scripts/create_layout_video.py
```

Reproduce `sample_data/table-layout-demo.avi` y activa **Mostrar regiones**. Al terminar sus tres segundos se conserva el último frame para ajustar las zonas. El vídeo anterior de captura es de 960 × 540 y muestra el aviso de resolución incompatible al activar el overlay.

Para una mesa real, utiliza un frame recibido por el backend de exactamente **1920 × 1080**, con la misma composición y seis asientos. Cambia el nombre de plataforma, ajusta todas las zonas y pulsa **Guardar layout**. Marca la comprobación manual solo cuando hayas revisado las 29 regiones. Cambiar coordenadas o plataforma vuelve a marcar la calibración como pendiente. El tamaño físico del monitor no basta: cuentan las dimensiones de la captura enviada, que aparecen bajo la previsualización.

El JSON se guarda en `backend/table_layouts/platform_1920x1080.json`. Compose monta ese directorio para conservar los cambios al recrear contenedores; en Linux debe ser escribible por el usuario del backend. Los cambios guardados se cargan al entrar en `/live`; los borradores se pierden al salir de la página. **Recargar layout** vuelve a leer el archivo y descarta el borrador. Si otra pestaña guardó antes, se rechaza la escritura antigua y se mantiene el borrador para revisarlo. No hay actualización automática entre pestañas.

El overlay escala con la vista en escritorio y móvil, pero se oculta si la resolución de origen no coincide. No intenta localizar la mesa ni compensar bordes, zoom o desplazamientos. Consulta el contrato y los límites en [fase 4](docs/phase-4.md).

## Reconocer cartas

Genera el vídeo de demostración:

```powershell
backend/.venv/Scripts/python backend/scripts/create_card_video.py
```

Con el layout inicial **Zeros demo**, reproduce `sample_data/cards-demo.avi` en `/live`. El panel **Cartas observadas** muestra Hero y board, similitud visual, lecturas pendientes/desconocidas y un historial de cambios. La demo dura 22 segundos: aparecen Hero, flop, turn y river; se interrumpe la imagen durante un segundo; se recupera; las zonas quedan vacías y reaparecen las mismas cartas de Hero. Se emiten siete eventos en total, sin repetirlos en cada frame.

Cada lectura necesita **tres frames consecutivos coincidentes**. Una lectura desconocida conserva las últimas cartas confirmadas y lo indica; una zona vacía también requiere confirmación. Las cartas duplicadas o lecturas ambiguas se rechazan. La similitud mostrada no es una probabilidad de acierto. El vaciado de una zona no se interpreta como final de mano ni como fold.

Solo se ha validado la baraja sintética incluida. Para una plataforma real necesitas las **52 referencias PNG**, un color de fondo vacío, un layout calibrado y el nombre de plataforma coincidente. Consulta el formato en [card_templates/README.md](backend/card_templates/README.md). `CARD_TEMPLATE_DIR` selecciona la carpeta de referencias; vacío usa la demo. En Compose, guarda el perfil bajo `backend/card_templates/` y configura su ruta `/app/card_templates/mi_perfil` en `.env`; recrea el servicio para aplicar la variable.

Layout y referencias se cargan al iniciar cada captura. Guardar coordenadas durante la reproducción modifica el overlay del editor; **reinicia la fuente para aplicar esos cambios al detector**. La guía del contrato, confirmaciones y límites está en [fase 5](docs/phase-5.md).

## Leer nombres e importes con OCR

Tesseract lee las regiones de nombres, stacks y apuestas de los seis asientos, además del bote y las ciegas. El panel **Lecturas de la mesa** muestra los valores confirmados y permite desplegar el texto original, confianza y tiempo de la última confirmación.

```powershell
backend/.venv/Scripts/python backend/scripts/create_ocr_video.py
backend/.venv/Scripts/python backend/scripts/create_hand_video.py
backend/.venv/Scripts/python backend/scripts/create_action_video.py
```

Reproduce `sample_data/ocr-demo.avi` en `/live`. Dura 16 segundos: empieza con bote 750, ciegas 50/100 y stack de Alice 12500; entre los segundos 5 y 7 se ocultan bote y stack; desde el segundo 8 pasan a 1500 y 12000, y la apuesta de Alice pasa de 0 a 500. Las cartas se reconocen simultáneamente.

El OCR procesa hasta dos muestras por segundo de fuente. Cada campo exige **tres coincidencias entre las últimas cinco muestras**, todas con confianza mínima del 80%, antes de confirmar un valor. Las lecturas ambiguas o vacías conservan el último valor e indican que ya no está confirmado por la imagen actual. Un campo vacío nunca se convierte en cero ni se interpreta como fold.

`OCR_DECIMAL_SEPARATOR` acepta `.` (predeterminado) o `,`. El formato se configura explícitamente, sin adivinar si `1.234` significa mil doscientos treinta y cuatro o un decimal. Se admiten agrupaciones de miles, hasta dos decimales, sufijos `k`/`M`, las unidades visibles `$`, `€`, `£` y `BB`, y ciegas en formato `small / big`. La API conserva importes exactos como cadenas decimales normalizadas con punto. Las cifras sin unidad permanecen sin unidad; no se infieren moneda ni conversiones.

Docker incluye Tesseract y el modelo inglés. En ejecución local puedes establecer `$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'` antes de arrancar el backend, si está instalado ahí. Para cambiar el separador en Compose, edita `.env` y recrea el servicio. Más detalles y límites en [fase 6](docs/phase-6.md).

## Desarrollo local en Windows

Requisitos: Python 3.14 y Node.js 24. Para OCR local se necesita además Tesseract con los datos de idioma `eng`, disponible en PATH o mediante `TESSERACT_CMD`. Docker ya incluye el motor. Sin Tesseract, la captura y las cartas siguen funcionando y el panel informa de que OCR no está disponible. Sin `DATABASE_URL`, el desarrollo local guarda manos en `data/hands.sqlite3` (ruta configurable con `HAND_DB_PATH`). Compose usa PostgreSQL. Detén Compose antes de usar los mismos puertos en local.

Terminal 1, desde la raíz:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
Set-Location backend
.venv/Scripts/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 4096
```

Terminal 2, desde la raíz:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Vite reenvía `/api`, `/health` y `/ws` al backend. Para otro puerto del backend, configura `API_PROXY_TARGET` antes de arrancar Vite. HTTP y WebSocket usan el mismo origen del navegador.

## Modos

`APP_MODE` acepta `LIVE_REAL_MONEY` (predeterminado) y `TRAINING`. El backend valida el valor al arrancar. No se cambia mediante mensajes del navegador.

Con Docker, cambia `.env` y ejecuta `docker compose up -d`. Para ejecución local, establece `$env:APP_MODE = 'TRAINING'` en la terminal del backend antes de arrancarlo; el archivo `.env` de Compose no se carga automáticamente en el proceso local.

El handshake declara `strategy_available: true` en `TRAINING`, indicando que existen los motores de estrategia, no que puedan recomendar en cualquier estado. En `LIVE_REAL_MONEY` permanece falso y `poker.analysis`, `preflop.result` y `strategy.result` son `null`. El filtrado se aplica en el backend, también al detener la captura. Los resultados preflop y de estrategia se guardan en archivos privados; su consulta/desbloqueo posterior aún no se implementa.

## Motor matemático

En `/live`, **Motor matemático** permite configurar Hero, rivales participantes, sus rangos y si el bote incluye las apuestas. Se actualiza con GameState sin leer vídeo. Los folds confirmados excluyen al rival; revisa los participantes en cada mano. La configuración se borra al cambiar la fuente. Rangos: `random`, `AA,KK,AKs`, `AKo`, combos `AsKh` y pesos como `AA:0.5,KK`. No se admiten `+` ni intervalos.

En entrenamiento se muestran bote total, stacks efectivos, SPR actual, importe a igualar, pot odds, equity mínima teórica y equity al showdown. Monte Carlo usa 1.000 muestras reproducibles e intervalo de muestreo; river heads-up enumera combos exactamente. Se omiten métricas con lecturas dudosas o datos insuficientes. No se generan recomendaciones ni EV.

Las fórmulas, límites, API y un entorno de entrenamiento independiente con pruebas de navegador están en [fase 12](docs/phase-12.md).

## Motor preflop

El panel **Estrategia preflop** permite confirmar, por mano, Hero, botón, asientos que recibieron cartas, antes totales y acciones previas. Las posiciones se derivan de esa disposición manual; se contrastan turno, apuestas y bote con el historial. Si falta información o el escenario no está cubierto, el motor explica el motivo y no sugiere una acción.

Las tablas configurables consideran posición, stack efectivo, jugadores, subida previa y antes. La tabla ilustrativa cubre la primera decisión de Hero con 20–200 BB y sin antes; no es GTO ni tiene confianza estratégica calibrada. El sizing indica la apuesta total en BB y cuánto añadir. Los resultados válidos se archivan con los datos disponibles en ese instante, sin usar acciones futuras.

Genera `sample_data/preflop-demo.avi` con `backend/.venv/Scripts/python backend/scripts/create_preflop_video.py`. En entrenamiento, configura Hero 3, botón 6, seis asientos, antes cero e historial `[]`. As Ks produce Raise hasta 2,5 BB; tras actuar Hero deja de mostrarse la sugerencia. Instrucciones de entorno, API, límites y pruebas en [fase 13](docs/phase-13.md).

### Motor postflop

«Motor matemático» incorpora mano formada, proyectos de color/escalera con cartas de finalización sin duplicados, backdoors, textura del board y contribuciones de apuestas respecto al bote inicial de la calle. La posición requiere confirmar botón y participantes para la mano actual. La comparación de rangos frente a un rival utiliza un rango manual de Hero, equity con intervalo de muestreo y un indicador limitado de densidad de nuts actuales. Equity de la mano y SPR siguen admitiendo multiway. No genera recomendaciones postflop. Desde la fase 16 admite elegir rangos manuales o adaptativos de rivales.

Prueba el panel en entrenamiento con `ocr-demo.avi`, Hero 2, rival 1 `QQ,KK,AKs`, rango de Hero `JJ,AA,AK`, botón 2 y bote que incluye apuestas. Marca la confirmación postflop y aplica. Guía completa, fórmulas y límites en [fase 14](docs/phase-14.md).

### Modelo de rivales

«Modelo de rivales» muestra VPIP, PFR, 3Bet, Fold to 3Bet del agresor inicial, CBet de flop, Fold to CBet, WTSD y AF postflop. Cada porcentaje incluye numerador, oportunidades e intervalo de confianza. Confirma participantes y botón antes de la primera acción: VPIP/PFR se consolidan al cerrar el preflop; las demás oportunidades se actualizan al resolverse. Las capturas parciales solo aportan las métricas que permiten sus datos; ver river no implica showdown.

Genera `sample_data/opponents-demo.avi` con `backend/.venv/Scripts/python backend/scripts/create_opponent_video.py`. En entrenamiento selecciona solo los asientos 1 y 2, botón 1 y confirma el inicio. La demo recorre raise, 3Bet, call, CBet, fold y final de mano. Los perfiles son independientes por captura y asiento; se archivan en SQLite/PostgreSQL. Fórmulas, límites y preparación del entorno en [fase 15](docs/phase-15.md).

### Rangos adaptativos

La fase 16 repondera combos después de cada call, bet o raise confirmado. Usa estadísticas anteriores a la mano, suavizadas con un prior configurable: la muestra recibe peso `n / (n + fuerza_del_prior)`. Check conserva el rango; fold retira al participante; las cartas del board eliminan combos imposibles. Los supuestos, tasas utilizadas y eventos quedan archivados. No clasifica ni decide solo por etiquetas de jugador.

En entrenamiento, confirma el inicio en «Modelo de rivales» y selecciona «Origen de los rangos → Adaptativos» en «Motor matemático». Asigna Hero y todos los rivales participantes. La demo `opponents-demo.avi` usa Hero 1 y rival 2. Rangos y comparación postflop se suspenden si falta contexto: no se sustituyen por rangos manuales. Fórmulas, límites, comandos y prueba guiada en [fase 16](docs/phase-16.md).

### Contexto del torneo

En «Modelo de rivales» puedes añadir buy-in, moneda, tipo de torneo, stack inicial en fichas, participantes totales, jugadores restantes y premios por tramos. Se confirman y archivan al inicio de la mano; no sustituyen los datos observados por OCR. Los premios desconocidos quedan sin confirmar y los importes conocidos se suman con precisión decimal.

El prior de población es una hipótesis manual opcional para ese buy-in y formato: permite establecer VPIP, PFR, 3Bet y una fuerza de 1 a 30 oportunidades. Su peso es `fuerza / (oportunidades + fuerza)`, por lo que las observaciones predominan cuando crece la muestra. Sin activarlo, el precio de entrada no cambia automáticamente los rangos. Guía, ejemplo y límites en [fase 17](docs/phase-17.md).

### Motor de estrategia

«Motor de estrategia» se activa en cada turno observado de Hero y muestra dos columnas: **baseline** y **explotativa**, con frecuencia, sizing y EV aproximado en BB por acción (por ejemplo, Call 72 % · Raise 28 %). Usa el Hero y la convención de bote del motor matemático. En preflop, la baseline es la acción de la tabla de «Estrategia preflop», sin ajustes. En postflop heads-up requiere el inicio confirmado en «Modelo de rivales».

La baseline supone un rival con priors genéricos que defiende de forma equilibrada; la explotativa usa su rango adaptativo, el prior de población del torneo y, en la CBet de flop de Hero, su Fold to CBet suavizado. Sin observaciones ambas coinciden; los datos ganan peso con `n / (n + k)`. El EV es de una sola decisión (sin re-subidas ni calles futuras) y las frecuencias se reparten con una función logit configurable. La etapa del torneo aplica un factor de riesgo ilustrativo, no ICM. Multiway y all-in quedan fuera.

Los resultados se archivan en privado antes de publicarse. En dinero real no se envían a la interfaz. Prueba con `opponents-demo.avi` en entrenamiento: Hero 1, rival 2, asientos 1 y 2 con botón 1; la decisión ante la CBet aparece entre los 52 y 56 s. Fórmulas, API y límites en [fase 18](docs/phase-18.md).

### Análisis de faroles

Dentro de «Motor de estrategia», «Análisis de farol» indica en cada decisión postflop heads-up si la mejor apuesta o subida de Hero es de valor, farol o semifarol y si rinde más que pasar. Muestra tamaño recomendado, fold necesario y estimado, efecto de las cartas de Hero sobre el rango del rival (bloqueadores y cartas que dejan intactos sus folds), valor de showdown, proyectos, textura, SPR, rangos percibidos y tendencias del rival, en versión baseline y explotativa.

Desde esta fase el rival decide qué parte de su rango continúa sin conocer las cartas de Hero; esas cartas cambian después el fold estimado. El fold explotativo usa Fold to CBet en la CBet de Hero y un proxy de WTSD en el resto, siempre suavizados hacia la defensa equilibrada. Es heurístico y sin calibrar; no planifica varias calles ni faroles preflop. Detalles en [fase 19](docs/phase-19.md).

## Decisiones de Hero

La fase 20 detecta `HERO_DECISION_REQUIRED` y guarda una `DecisionSnapshot` inmutable: cartas, board, bote, stacks, acciones previas, rangos ponderados completos, estadísticas y configuración. La estrategia utiliza esos datos congelados; cambiar la configuración afecta a las siguientes decisiones. El reparto de combos de igual fuerza en el modelo de faroles se realiza ahora proporcionalmente, sin desempates por el nombre de las cartas (`ev-logit-v3`).

En entrenamiento, «Decisiones de Hero» permite abrir el momento guardado incluso después de que Hero actúe. El detalle y listado también se consultan mediante `/api/decisions/{id}` y `/api/decisions?hand_id=…`. Los huecos y modelos no disponibles se conservan explícitamente; no se completan con información futura. En dinero real el archivo permanece privado hasta cumplir la política de revisión. Guía y pruebas en [fase 20](docs/phase-20.md).

## Evaluación después de actuar

La fase 21 vincula la primera acción confirmada de Hero con su instantánea y compara su EV con la mejor opción baseline/explotativa configurada. Un tamaño distinto se evalúa exactamente con el mismo modelo y los mismos datos anteriores. La diferencia no representa el dinero ganado o perdido en la mano. Preflop compara con la tabla sin inventar un EV; la confianza estratégica se expresa como limitada o insuficiente, sin porcentaje calibrado.

En entrenamiento abre «Decisiones de Hero → Ver decisión → Después de actuar». La evaluación queda archivada y sobrevive a recargas y reinicios; los trabajos pendientes se recuperan desde la base. La API es `/api/decisions/{id}/evaluation`. En dinero real se abre según la política de la fase 22. Contrato del cálculo, límites y ejemplo en [fase 21](docs/phase-21.md).

## Revisión según modo

La fase 22 permite configurar en `/live` el «Momento de revisión» antes de iniciar cada captura: tras `HAND_FINISHED` o tras `SESSION_FINISHED` (predeterminado). La política queda guardada con esa captura y no cambia retroactivamente. Durante una mano activa en dinero real solo se muestran datos descriptivos, incluidos los recuentos y estadísticas observadas; rangos y recomendaciones permanecen privados.

Abre **Manos → una mano → Revisión de la mano**. Con la primera política basta un final de mano confirmado y persistido. Con la segunda, detén la captura, marca que has terminado la sesión de juego y pulsa **Finalizar sesión y abrir revisión**. El final del vídeo, una desconexión o un reinicio no finalizan la sesión de juego. Por ahora una captura equivale a una sesión de revisión; no hay agrupación de varias capturas.

La revisión presenta los datos congelados, acción real, diferencia de EV, alternativas baseline/explotativas y faroles disponibles. Una nueva mano activa o el inicio de otra captura vuelven a ocultar incluso las revisiones anteriores. El backend verifica el acceso en cada consulta. Las manos antiguas requieren cierre explícito de su sesión. `FEEDBACK_RELEASE` define la preferencia inicial al arrancar; el selector cambia la preferencia para próximas capturas hasta reiniciar, sin modificar las políticas ya archivadas. Guía completa y pruebas en [fase 22](docs/phase-22.md).

## Pruebas

Backend, desde la raíz:

```powershell
backend/.venv/Scripts/python -m pytest backend -p no:cacheprovider
backend/.venv/Scripts/python backend/scripts/create_sample_video.py
backend/.venv/Scripts/python backend/scripts/create_layout_video.py
backend/.venv/Scripts/python backend/scripts/create_card_video.py
backend/.venv/Scripts/python backend/scripts/create_ocr_video.py
```

La suite local omite las cuatro pruebas que requieren Tesseract si no está en PATH. Para incluir el motor real, desde la raíz:

```powershell
docker compose build backend
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm zeros-backend-tests
```

El contenedor de pruebas es independiente de los servicios de la aplicación y no modifica su layout. La prueba opcional de PostgreSQL requiere una base exclusiva mediante `HAND_TEST_POSTGRES`; el comando está en [fase 11](docs/phase-11.md).

Frontend, desde `frontend/`:

```powershell
npm run build
npx playwright install chromium
npm test
```

Las pruebas de navegador requieren frontend y backend en marcha, los seis vídeos de prueba generados (incluidos `backend/scripts/create_hand_video.py` y `backend/scripts/create_action_video.py`), Tesseract disponible en el backend, el layout **Zeros demo**, `CARD_TEMPLATE_DIR` vacío y `OCR_DECIMAL_SEPARATOR=.`. Detén cualquier captura y evita editar el layout durante las pruebas: modifican la configuración para comprobar persistencia y restauran su contenido al terminar. Guardan manos de demostración en el archivo de la aplicación. Usan la API y el WebSocket reales. `E2E_BASE_URL` permite indicar otra URL de frontend. Los escenarios de captura se ejecutan en serie porque el backend admite una sola fuente.

La suite adicional `npm run test:training` usa una instancia separada en puerto 5174 y también requiere `preflop-demo.avi` y `opponents-demo.avi`. `npm run test:review` comprueba ambas políticas en modo real sobre el puerto 5173. Ejecuta backend y las tres suites de navegador secuencialmente: varios OCR simultáneos pueden saturar el equipo y provocar pérdida de señales. La preparación está en [fase 22](docs/phase-22.md).

Comprobación manual:

1. Abre `/` y espera «Backend conectado» y una latencia numérica.
2. En `/live`, pulsa «Comprobar conexión» y comprueba el mensaje de respuesta.
3. Abre `/sessions`: debe mostrar un estado vacío, sin manos inventadas.
4. Abre `/session/prueba` y recarga: debe mostrar «Sesión no encontrada».
5. Detén el backend: el estado pasa a «Reconectando…». Vuelve a arrancarlo y espera la recuperación automática.

## Estado de la partida

En `/live`, el panel **Estado de la partida** reúne Hero, board, calle observada, bote, ciegas y seis asientos con nombre, stack y apuesta. Muestra el tiempo de confirmación por campo y señala los últimos valores conservados durante lecturas dudosas. **Cambios confirmados** permite revisar los valores anteriores y nuevos, sin duplicar cambios por recibir frames idénticos.

Puedes probarlo con `sample_data/ocr-demo.avi`: se confirma flop, bote 750 y stack 12500; durante la ocultación conserva los importes y luego confirma bote 1500, stack 12000 y apuesta 500. Una captura nueva reinicia el estado y el historial.

La API añade `observation_state.game_state` a `GET /api/capture`, con snapshots independientes, importes decimales exactos, evidencia por campo y las últimas 40 revisiones. Las regiones pueden haberse confirmado en momentos distintos. Las manos reciben identidad y estado desde la fase 9; la fase 10 incorpora turno visual y acciones corroboradas. Botón y posiciones siguen pendientes. Un stack cero por sí solo no prueba all-in. Base del contrato en [fase 7](docs/phase-7.md).

## Eventos y reproducción del historial

El panel **Eventos de la partida** de `/live` muestra los eventos confirmados de cartas y estado con secuencia, tiempo de fuente y confianza disponible. **Exportar historial disponible (JSON)** descarga los últimos 40 eventos y un estado de referencia para reproducirlos sin vídeo:

```powershell
backend/.venv/Scripts/python backend/scripts/replay_events.py C:\ruta\zeros-events.json
```

La API `GET /api/events?scope_id=…&after=0` ofrece el mismo historial con cursor; el `scope_id` se obtiene de `GET /api/capture`. Si se descartaron eventos antiguos lo indica con `gap=true` y entrega el checkpoint disponible. Una captura distinta devuelve 409. Desde la fase 9, las manos y sus eventos se guardan automáticamente en la base de datos y se consultan mediante `/api/hands`.

El vídeo emite hechos de cartas y estado, además de `HAND_STARTED` y `HAND_FINISHED` cuando confirma límites de mano. Un EOF o una parada con mano activa genera `CAPTURE_ENDED` y archivo incompleto. Los eventos `PLAYER_*` incluyen las acciones corroboradas por el motor de la fase 10. Base del flujo en [fase 8](docs/phase-8.md).

## Manos guardadas

Reproduce `sample_data/hands-demo.avi`, generado con `backend/scripts/create_hand_video.py`. El panel **Manos observadas** separa dos manos: una termina al retirarse las cartas; la otra queda incompleta al finalizar el vídeo. Una ocultación breve no cierra la mano. El motor combina señales y evita cerrar una mano solo porque Hero se retire.

Consulta `/hands` o el enlace de la captura para ver las manos y sus eventos. El archivo persiste al recargar o reiniciar el backend. Las API `/api/hands` y `/api/hands/{id}` ofrecen paginación. El límite de 40 eventos afecta al historial en memoria; los eventos guardados se mantienen en la base de datos.

Las manos activas al reiniciar el proceso se marcan incompletas. Un fallo de escritura detiene la captura y conserva lo pendiente para reintentar antes de iniciar otra fuente. Usa un solo worker de backend. Las señales, límites y comprobaciones se detallan en [fase 9](docs/phase-9.md).

## Acciones reconstruidas

Genera `sample_data/actions-demo.avi` con `backend/.venv/Scripts/python backend/scripts/create_action_video.py` y reprodúcelo en `/live`. En 56 segundos, el perfil **Zeros demo** muestra seis acciones: check, bet, call, raise, fold y all-in. El panel de eventos muestra su asiento, apuesta total y señales; el detalle en `/hands` conserva ese historial.

El motor exige un turno visual y una etiqueta de acción estables, junto a stacks, apuestas y bote coherentes. No interpreta zonas vacías como fold/check ni un stack cero aislado como all-in. Las acciones ambiguas se omiten y el historial puede quedar incompleto. Las referencias visuales solo cubren la demo sintética; todavía no hay reconocimiento de etiquetas de salas reales. Reglas, límites y pruebas en [fase 10](docs/phase-10.md).

## Organización

```text
backend/
  app/
    api/                 Salud y contratos iniciales de sesiones
    websocket_engine/    Conexión, suscripción y broadcast de captura con colas limitadas
    capture_engine/      Fuentes, ciclo de captura y previsualización
    pipeline_engine/     Cola limitada, productor, procesador y métricas
    vision_engine/       Observaciones de cartas con layout congelado por captura
    card_detector/       Referencias, segmentación y comparación visual de cartas
    ocr_engine/          Recortes, preprocesamiento, Tesseract y normalización
    game_state_engine/   Estado inmutable, evidencia, estabilización y diferencias
    event_engine/        Contratos, eventos, retención, cursores y reproducción
    hand_reconstructor/  Límites de mano, archivo transaccional y consultas
    action_engine/       Turno y etiquetas visuales, corroboración de acciones
    poker_engine/        Métricas, rangos, equity y cálculo acotado con filtrado por modo
    strategy_engine/     Tablas preflop, baseline/explotativa por EV, faroles, servicio y archivo privado
    decision_engine/     Instantáneas inmutables, evaluación de acciones y cola persistente privada
    opponent_model/      Estadísticas, rangos adaptativos y entrada congelada de decisión
    tournament_context/  Torneo, premios, prior de población y etapa/riesgo
    table_detector/      Esquema, validación y guardado de regiones configuradas
    config.py            Modo validado al inicio
    main.py              Construcción de FastAPI
  tests/                 Pruebas de API y WebSocket
  scripts/               Generador del vídeo de prueba
  table_layouts/         Layout único de 1920 × 1080 y seis asientos
  card_templates/        Formato y carpetas de referencias externas
frontend/
  src/
    components/          Navegación, iconos y registro
    live/                Protocolo, reconexión y resumen de la mano actual
    capture/             Controles, envío de pantalla y preview
    table/               Editor de regiones y overlay de depuración
    cards/               Lecturas confirmadas y eventos de cartas
    ocr/                 Nombres, importes, confianza y lecturas originales
    game/                Estado integrado y revisiones descriptivas
    events/              Historial estructurado y exportación
    hands/               Seguimiento y consulta de manos guardadas
    poker/               Configuración del cálculo y resultados de entrenamiento
    preflop/             Contexto por mano, tablas y resultados preflop en entrenamiento
    opponents/           Estadísticas, contexto de mano y rangos adaptativos
    tournament/          Formulario y resumen del torneo
    strategy/            Baseline, explotativa y análisis de farol en cada decisión de Hero
    decisions/           Revisión de instantáneas y comparación de acciones en entrenamiento
    pages/               Las cuatro páginas solicitadas
  tests/                 Pruebas de navegador
docs/
  phase-1.md             Alcance, protocolo y validación
  phase-2.md             Captura, límites y pruebas
  phase-3.md             Pipeline, métricas y pruebas de sobrecarga
  phase-4.md             Configuración, calibración y overlay
  phase-5.md             Reconocimiento de cartas y estabilidad temporal
  phase-6.md             OCR, formatos numéricos y confirmación de importes
  phase-7.md             GameState, evidencia y comparación temporal
  phase-8.md             Eventos estructurados, cursores y reproducción sin vídeo
  phase-9.md             Detección de límites de mano y persistencia
  phase-10.md            Inferencia de acciones mediante múltiples señales
  phase-11.md            Vista en directo y suscripción WebSocket
  phase-12.md            Motor matemático, rangos, Monte Carlo y separación de modos
  phase-13.md            Baseline preflop configurable y archivo privado de resultados
  phase-14.md            Análisis postflop, proyectos, textura y comparación de rangos
  phase-15.md            Estadísticas de rivales, oportunidades, confianza y archivo
  phase-16.md            Rangos adaptativos, priors y cálculo con pesos por combo
  phase-17.md            Configuración de torneo, premios y prior opcional de población
  phase-18.md            Motor de estrategia: EV aproximado, frecuencias y ajustes
  phase-19.md            Análisis de faroles, bloqueadores y fold equity
  phase-20.md            Punto de decisión, corte temporal e instantáneas inmutables
  phase-21.md            Acción real frente a estrategia, diferencia de EV y recuperación
  phase-22.md            Política de revisión, cierre de sesión y feedback según modo
compose.yaml
```

Solo se crean módulos que tienen una responsabilidad implementada en esta fase.

## Limitaciones y siguiente fase

Se guardan manos, eventos, instantáneas y evaluaciones de decisiones, incluidas acciones corroboradas en el perfil sintético. Hay una baseline preflop limitada a contextos confirmados, estrategias postflop heads-up aproximadas y revisión diferida en dinero real; todavía no hay agrupación de varias capturas en sesiones. No se garantiza una hand history completa con señales ausentes, apuestas simultáneas o imágenes sin calibrar. La ilustración de la portada es decorativa. El registro de actividad conserva mensajes de conexión; los paneles de cartas y eventos muestran observaciones y acciones inferidas. La tipografía DM Sans y Manrope se sirve localmente; sus licencias OFL se incluyen en `frontend/public/fonts/`.

La reproducción inicial está pensada para archivos de FPS constante, sin audio, pausa, búsqueda o bucle. La entrada de archivo se limita a 8.294.400 píxeles por frame; la pantalla se adapta a un máximo de 1920 × 1080. El JPEG de previsualización se adapta a 1280 × 720. Los FPS son un objetivo configurable, no una garantía de rendimiento. Las pestañas en segundo plano pueden sufrir limitaciones del navegador.

La cola, las ventanas de métricas y los frames retenidos están acotados. La parada espera al trabajo nativo en curso antes de liberar recursos; no puede interrumpir a la fuerza un decodificador o una futura inferencia que se bloquee. No se ha validado todavía una sesión de 8 horas.

El detector inicial requiere cartas claras, completas, verticales y separadas dentro de las zonas configuradas. No está validado para cámaras, cartas inclinadas, dorsos, animaciones ni temas de salas reales. Su historial conserva los últimos 40 eventos por captura en memoria; las lecturas llegan a la interfaz mediante snapshots WebSocket. Una conexión lenta puede omitir snapshots intermedios; el archivo de manos conserva los eventos persistidos.

La siguiente fase prevista es la 23: timeline de decisiones y acceso al frame exacto. La calibración y validación de una plataforma real siguen pendientes; no se ha probado una sesión real de ocho horas ni una entrada de cámara.
