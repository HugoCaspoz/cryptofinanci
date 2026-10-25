# Fase 24 - Explicador de decisiones

## Qué se ha construido

La fase anterior se validó con Docker, Tesseract y PostgreSQL antes de continuar: 566 pruebas correctas sin omisiones. Los snapshots y evaluaciones existentes siguen siendo la fuente del análisis.

Se incorpora app/llm_explainer y un panel de explicaciones en las revisiones de manos y decisiones, y junto a la estrategia en directo de TRAINING cuando existe una instantánea de Hero. La generación es manual y ofrece Simple y Avanzado. Simple describe contexto, frecuencias, equity, pot odds y comparación cuando están disponibles. Avanzado añade importes del motor, EV por alternativa, acciones previas, rangos resumidos, muestras de rivales, SPR, torneo y faroles si esos datos existen.

El LLM actúa como editor: recibe frases y referencias creadas a partir de los resultados estructurados, selecciona/ordena identificadores existentes y el servidor renderiza las frases originales. No se acepta prosa libre del proveedor. Esto conserva las cifras, tamaños y acciones del motor; tampoco permite al modelo convertir frecuencias en una certeza, atribuir cartas al rival o generar una estrategia distinta. Los hechos obligatorios incluyen contexto, las dos estrategias y los límites, además de la comparación y el aviso de historial parcial cuando corresponden. Avanzado conserva todos los hechos disponibles.

## Fuente y corte temporal

El endpoint lee el snapshot y su evaluación guardados. Si aún no hay evaluación, busca una estrategia ya archivada vinculada exactamente a la identidad, mano, modo, scope y frame del snapshot. No llama al motor matemático ni reinterpreta decisiones con rangos o estadísticas actuales. La acción posterior de Hero aparece solo como hecho de comparación de la evaluación existente, sin incorporar su state_after ni cartas posteriores.

El contexto externo se limita a esas frases y referencias. No contiene capturas, vídeo, nicknames, texto OCR, credenciales ni todos los combos de los rangos; se usan sus resúmenes. Los snapshots completos siguen en el archivo local del servidor.

## Proveedor y configuración

Por defecto EXPLAINER_PROVIDER=local: no hay peticiones externas. Para habilitar OpenAI, en el archivo .env de Compose:

```dotenv
EXPLAINER_PROVIDER=openai
OPENAI_API_KEY=<tu clave del servidor>
OPENAI_MODEL=<modelo compatible disponible en tu cuenta>
```

Aplicar con:

```powershell
docker compose up -d
```

La clave solo pasa al backend y se excluye de la representación de Settings. No existe formulario de claves ni endpoint que las publique. En ejecución local se necesitan esas variables en la terminal del backend; no se carga el .env de Compose automáticamente.

Se usa POST https://api.openai.com/v1/responses, sin herramientas, con store=false y una salida JSON Schema estricta que solo permite identificadores de hechos. No se impone un modelo por defecto: debe configurarse uno compatible. El timeout es de 12 segundos, la respuesta se limita a 64 KiB y no hay reintentos automáticos. El contrato se comprobó con [OpenAI Docs: Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) y [Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses). store=false desactiva el almacenamiento de la respuesta para su recuperación mediante API; no equivale por sí solo a una garantía de retención cero por el proveedor.

Si falta clave/modelo, hay un error, timeout, rechazo, respuesta incompleta, texto extra, identificadores inventados, repeticiones o hechos obligatorios omitidos, se muestra una explicación local identificada como tal. No se muestra el error privado del proveedor. Un fallo externo no se guarda como éxito de OpenAI: se puede reintentar con otro clic.

## API, caché y permisos

```text
POST /api/decisions/{id}/explanation
{"style":"simple"|"advanced"}
```

Devuelve versión, identidad, estilo, proveedor/modelo, motivo de respaldo cuando existe, párrafos con referencias y si se reutilizó la caché. Sin resultado de estrategia guardado responde 409; una generación ya en marcha responde 429 con Retry-After. Solo se admite un trabajo nuevo simultáneo por instancia, fuera del pipeline de captura. No se generan explicaciones por frame.

La tabla decision_explanations guarda una caché persistente en SQLite/PostgreSQL. La clave incluye versión de hechos, snapshot, contenido explicable, estilo, proveedor y modelo. Si se completa después la evaluación, cambia el contenido explicable y se obtiene una entrada nueva. La lectura de caché no evita comprobar permisos.

La API aplica las mismas políticas por mano/sesión que decisiones y evaluaciones, antes de leer/generar y tras las esperas. Una nueva captura en dinero real revoca también explicaciones ya guardadas. Respuestas con Cache-Control: no-store, private. En la interfaz, la identidad, estilo, instancia, captura y revisión de permisos forman la clave de presentación; las peticiones se cancelan y el texto se oculta al cambiar contexto o perder conexión.

## Archivos

- Backend nuevo: app/llm_explainer/{models,facts,provider,service,routes}.py.
- Configuración, ciclo de vida y persistencia: app/config.py, main.py, hand_reconstructor/store.py, compose.yaml y .env.example.
- app/version.py centraliza fase 24 y versión; salud HTTP y handshake WebSocket utilizan el mismo dato.
- Frontend: explanations/ExplanationPanel.tsx y explanations.css; integración en feedback/HandReview, decisions/DecisionPanel y strategy/StrategyPanel; tipos y portada actualizados.
- Pruebas: backend/tests/test_explanations.py y test_api.py; timeline, entrenamiento y revisión de navegador ampliados. La fixture seed_timeline_review.py acepta --serve para levantar una instancia temporal aislada.
- README.md, este documento y validación posterior en phase-23.md.

## Ejecutar y probar

```powershell
docker compose up --build -d --wait
```

Abrir http://localhost:5173. En Manos, seleccionar una mano y una decisión desbloqueadas; pulsar Generar explicación. Cambiar el selector a Avanzado y generar para ver los detalles. Una recarga conserva la caché del servidor. En modo real no se muestra el texto mientras la revisión está bloqueada. En TRAINING, el panel de estrategia ofrece el mismo botón durante turnos confirmados de Hero.

Backend completo con una base exclusiva de pruebas, creada previamente y diferente de la base de la aplicación:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase24_checks zeros-backend-tests
```

Frontend desde frontend/:

```powershell
npm run build
npm run format:check
```

La prueba sintética de timeline y explicación utiliza la fixture y las variables descritas en phase-23.md. En Docker se puede ejecutar el script de la imagen de tests con --serve y conectarle una interfaz temporal. Las suites de entrenamiento y revisión se ejecutan secuencialmente para no competir por OCR; TRAINING_E2E_URL y REVIEW_E2E_URL permiten apuntarlas a instancias auxiliares. E2E_BROWSER_CHANNEL=msedge usa Edge instalado.

## Validación

- Backend completo en Docker con Tesseract y PostgreSQL exclusivo: **583/583 correctas**, sin omisiones, en 117,70 s. Incluye adaptador OpenAI simulado, respuestas inválidas, timeout/respaldo, caché persistente, estilos, ausencia de recálculo, permisos/revocación e imágenes en PostgreSQL.
- TypeScript/Vite y npm run format:check: correctos.
- Navegador general y timeline/explicaciones con fixture Docker: **7/7 correctas**, con Simple/Avanzado, imagen y estado congelados, escritorio de 1440 px y móvil de 390 px; capturas revisadas visualmente.
- Revisión con vídeo sintético generado en Docker: **2/2 correctas**, políticas SESSION_FINISHED y HAND_FINISHED, con imagen, Simple/Avanzado y revocación de explicaciones al iniciar otra captura; 2,4 min.
- Entrenamiento en directo con vídeo: **1/1 correcto**, generación de explicación durante el turno, archivo y comparación posterior sin duplicar paneles, escritorio/móvil y recarga; 1 min.
- Las instancias auxiliares se detuvieron al finalizar. Compose principal quedó sano en LIVE_REAL_MONEY, PostgreSQL y sin captura activa, con explicador local predeterminado.

Durante la comprobación de entrenamiento se detectó una clave React duplicada entre evaluación y explicación, que podía duplicar secciones al actualizarse el estado. Se separaron las claves y se añadió una comprobación de que hay exactamente un panel de cada tipo.

La primera ejecución de PostgreSQL detectó una fixture de prueba que emitía un evento con el scope de otra captura; se corrigió la fixture y la suite completa posterior pasó. En el navegador, un vídeo sintético generado localmente con OpenCV 4.11 produjo cartas desconocidas en el detector de Docker, que usa OpenCV 5.0. Se regeneró dentro del mismo contenedor: la lectura pasó a As/Kh con similitudes de 0,9835 y 0,9821, sin modificar umbrales.

Para las demos, conviene generar las referencias y el vídeo con la misma versión de OpenCV. Desde la raíz, con la imagen de tests construida:

```powershell
docker run --rm -v C:/code/poker/sample_data:/samples zeros-backend-tests python scripts/create_opponent_video.py --output /samples/opponents-demo.avi
```

## Límites y fase siguiente

La explicación está deliberadamente limitada al vocabulario de hechos implementado. OpenAI organiza material ya redactado; no hay chat abierto ni razonamiento libre. La calidad no supera la del detector, los rangos ni el motor heurístico. Sin estrategia guardada se muestra que no se puede explicar, sin fabricarla. La caché crece con las decisiones/estilos y no tiene una política de retención automática.

No se enviaron peticiones de pago a OpenAI durante esta entrega; el adaptador se valida con transporte simulado y el flujo real funciona con el respaldo local. Para verificar la cuenta y modelo elegidos hace falta configurarlos en el servidor y solicitar una explicación.

La siguiente fase prevista es la 25: medir latencias de captura, visión, actualización de estado y análisis. No forma parte de esta entrega.
