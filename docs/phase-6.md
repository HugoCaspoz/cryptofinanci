# Fase 6 — OCR en directo

## Construido

Se leen **20 regiones** del layout: bote, ciegas y nombre, stack y apuesta de cada uno de los seis asientos. El nuevo `ocr_engine` recorta y prepara las imágenes, invoca Tesseract y devuelve texto original, confianza, valor normalizado y unidad explícita. `game_state_engine/ocr_state.py` confirma esas lecturas temporalmente. El panel **Lecturas de la mesa** muestra los resultados, pendientes e ilegibles, y un desplegable con el diagnóstico de cada campo.

La validación se ha realizado con texto sintético sobre el layout Zeros demo. No se dispone todavía de una captura real de una plataforma. OCR no depende de las referencias de cartas: puede funcionar aunque estas falten, siempre que el layout tenga la resolución correcta y, fuera de la demo, esté calibrado. Ambos modos conservan `strategy_available: false`.

## Procesamiento

El layout se toma de la copia fijada al iniciar la captura. Se muestrea como máximo cada 0,5 segundos de **tiempo de fuente**, sobre frames distintos. Con una fuente de 5 FPS, la separación efectiva suele ser 0,6 segundos. Los frames no muestreados siguen pasando por el detector de cartas y no cuentan como nueva evidencia OCR.

Cada recorte pasa por escala de grises, suavizado gaussiano para reducir ruido de compresión, ampliación, normalización de contraste y umbral de Otsu. Se ajusta la polaridad a texto oscuro sobre fondo blanco y se añade margen. Los veinte recortes se colocan en filas separadas de una imagen de 1024 × 1920: una sola invocación de Tesseract por muestra, en lugar de veinte procesos.

Tesseract recibe el PNG por entrada estándar y devuelve TSV. La asignación de palabras a regiones usa sus coordenadas verticales, conservando los huecos entre filas vacías y rechazando tokens que cruzan filas. La confianza de una región es la menor de sus palabras. Un recorte sin contraste se marca sin texto incluso si el motor devuelve caracteres espurios. Se utiliza el idioma `eng`, segmentación `--psm 6`, un thread OpenMP y un límite de dos segundos por invocación. El motor no escribe capturas temporales.

Las salidas TSV proporcionan texto, geometría y confianza; consulta [la documentación de Tesseract](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html). La preparación sigue sus recomendaciones sobre escala, ruido, contraste, umbral y márgenes de [calidad de entrada](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).

El proceso OCR corre dentro del worker de visión, fuera del event loop y separado del worker de captura. Si el análisis tarda más que la entrada, sigue funcionando el descarte de frames antiguos de la fase 3. El OCR puede reducir la tasa de procesamiento; dos muestras por segundo es un máximo, no una garantía.

## Normalización conservadora

- Importes: `Decimal`, sin redondeo binario, salida como cadena exacta. Hasta dos decimales y límite de 10¹².
- Separador decimal explícito mediante `OCR_DECIMAL_SEPARATOR`: punto o coma. El otro separador solo se acepta en agrupaciones completas de tres cifras.
- Sufijos `k` y `M` se convierten a 1000 y 1000000. Se conservan las unidades visibles `$`, `€`, `£`, `BB`; una cantidad sin unidad no se convierte automáticamente en fichas.
- Ciegas: dos cantidades positivas en formato `small / big`, con small menor o igual a big y sin unidades incompatibles.
- Nombres: hasta 32 caracteres alfanuméricos, guion, punto o guion bajo. No se fusionan automáticamente nombres que el OCR separó con espacios.
- Letras en números, textos como `All-in`, signos negativos, separadores inconsistentes y formatos no soportados se rechazan. No se transforma `125OO` en `12500`.

El texto leído se conserva aunque no pueda interpretarse. Las cadenas numéricas normalizadas usan siempre punto decimal; el separador configurado describe la entrada. No se convierten divisas ni valores a BB.

## Estabilización y datos desactualizados

Cada campo mantiene una ventana acotada a **cinco muestras OCR reales**. Se confirman valor y unidad cuando la lectura actual es válida y coincide con al menos tres entradas de la ventana, cada una con confianza mínima de 0,80. Las muestras utilizadas no pueden tener más de seis segundos de antigüedad. Una separación superior a 2,5 segundos reinicia la ventana.

Ejemplo: `12500`, `12500`, `125OO`, `12500` confirma `12500` en la cuarta muestra: la tercera no aporta voto, pero tampoco obliga a borrar una lectura fiable. Un nuevo valor aislado queda pendiente. Una muestra de baja confianza o vacía conserva el último valor confirmado y marca el campo como desconocido.

No se interpreta un campo vacío como cero. El cero solo se acepta cuando ha sido leído explícitamente y cumple la misma regla de confirmación. La confianza mostrada es una puntuación del OCR, no una probabilidad calibrada de acierto. Tres repeticiones no eliminan un error sistemático de lectura.

Los fallos de motor y de resolución invalidan las ventanas, manteniendo los valores antiguos identificados como desconocidos. Al cambiar de captura se reinician todos los campos. Tras parar o llegar al final del vídeo, los últimos resultados quedan visibles con un aviso. Cada campo conserva el frame y tiempo de fuente de su última confirmación.

Las regiones se confirman de manera independiente: este panel todavía **no es un GameState coherente de una mano**. No asigna identidades persistentes a jugadores, no deduce acciones por cambios de stack y no emite eventos de apuestas.

## Contrato y configuración

`GET /api/capture` añade `observation_state.ocr`:

```text
status, layout_revision, decimal_separator
last_sample_frame_id, last_sample_timestamp
fields:
  pot, blinds
  players.0.nickname, players.0.stack, players.0.bet
  ... hasta players.5
```

Cada campo contiene `key`, `kind`, `value`, `unit`, `confidence`, `raw_text`, `latest_confidence`, `status`, `confirmed_frame_id` y `confirmed_timestamp`. `value` es nulo hasta confirmar una lectura. `confidence` pertenece al valor confirmado; `latest_confidence`, al último texto leído. Los estados por campo son `waiting`, `pending`, `confirmed` y `unknown`.

Los estados globales distinguen espera, lectura disponible, motor no instalado, error, timeout, layout no disponible, resolución incorrecta y calibración pendiente. Un fallo OCR no detiene el vídeo ni el detector de cartas. La interfaz usa el sondeo HTTP de captura existente, cada 500 ms.

`OCR_DECIMAL_SEPARATOR` se fija al arrancar el backend; el valor predeterminado es `.`. En Windows local, `TESSERACT_CMD` permite indicar la ruta del ejecutable. Compose utiliza el ejecutable Linux incluido en la imagen y solo necesita la variable del separador. Guardar cambios del layout exige reiniciar la captura para aplicarlos al detector.

## Archivos

Nuevos:

- `backend/app/ocr_engine/`: modelos, preprocesamiento, adaptador Tesseract, normalización, coordinación y demo.
- `backend/app/game_state_engine/ocr_state.py`.
- `backend/scripts/create_ocr_video.py`.
- `backend/tests/test_ocr.py` y `test_ocr_integration.py`.
- `backend/Dockerfile.test` y su `.dockerignore` para comprobar el OCR real sin instalarlo en Windows.
- `frontend/src/ocr/{types,OcrPanel}` y `frontend/src/styles/ocr.css`.
- `frontend/tests/ocr-scenario.ts` y este documento.

Actualizados: VisionEngine, GameStateEngine, construcción/configuración del backend, salud y handshake, Dockerfile, Compose, `.env.example`, contratos TypeScript, Live, versión, portada, estilos, pruebas existentes y README. Se conserva `app.md`. No se añaden dependencias Python; la nueva dependencia del sistema es Tesseract con `eng`, instalada en Docker.

## Ejecutar y probar

Desde la raíz:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_ocr_video.py
```

Abre http://localhost:5173/live y reproduce `sample_data/ocr-demo.avi`. Su secuencia dura 16 segundos:

1. Bote 750, ciegas 50/100, seis nombres, stacks desde 12500 y apuestas visibles de cero.
2. Entre 5 y 7 segundos se ocultan bote y stack del asiento 1: se conservan los valores y se indica que no son legibles.
3. Desde el segundo 8, el bote pasa a 1500, el stack del asiento 1 a 12000 y su apuesta a 500, tras la confirmación temporal.
4. Las cartas A♠ J♥ y el flop J♠ 7♣ 4♦ permanecen reconocidos sin eventos duplicados.
5. Abre **Ver lecturas originales y confianza** para revisar el texto y puntuación de cada zona.

Pruebas completas de backend, con Tesseract real en un contenedor independiente:

```powershell
docker compose build backend
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm zeros-backend-tests
```

Alternativa local:

```powershell
backend/.venv/Scripts/python -m pytest backend -q -o cache_dir=.pytest_cache_phase6
```

Si `tesseract` no está en PATH, las tres pruebas que requieren el motor real se omiten explícitamente. La ruta `TESSERACT_CMD` permite ejecutar la aplicación local, pero las pruebas de integración buscan `tesseract` en PATH; usa Docker para validar el entorno completo sin instalar herramientas globales.

Para navegador, genera también los tres vídeos de las fases anteriores. Usa el layout Zeros demo, `CARD_TEMPLATE_DIR` vacío, separador punto y un backend con Tesseract. Desde `frontend/`:

```powershell
npm run build
npm run format:check
npm test
```

## Validación y limitaciones

Resultado final: **140 pruebas de backend aprobadas en Docker con Tesseract 5.5.0 y 12 pruebas de navegador aprobadas**. En Windows sin Tesseract se comprobaron 137 pruebas y se omitieron explícitamente las tres de integración real. La compilación del frontend y la comprobación de formato pasan. Se revisaron las vistas de escritorio y móvil; los tres servicios de Compose están saludables y no se observaron errores del pipeline en los logs revisados. Pytest conserva dos avisos de deprecación previos de Starlette/AnyIO.

Antes de implementar se verificó la fase 5: 109 pruebas de backend y 11 de navegador. Las nuevas pruebas comprueban normalización exacta, locales explícitos, formatos ambiguos, unidades, vacíos, confianza baja, tres votos entre cinco, no contar frames sin OCR, ventanas limitadas, errores/timeout, geometría TSV y ambas polaridades de texto. Las pruebas de integración usan Tesseract real sobre los 20 campos comprimidos y sobre un vídeo que oculta valores previamente confirmados.

Durante la validación apareció una lectura de ciegas correcta pero de baja confianza tras compresión JPEG. Se añadió suavizado previo, manteniendo el umbral del 80%. Un cero aislado leído como `Q` se rechaza; la demo muestra ceros explícitos como `0.00`, normalizados a `0`. No se han introducido sustituciones automáticas de letras por cifras.

El OCR requiere texto legible, horizontal, recortado dentro de sus regiones. Solo se incluye el modelo inglés. No están validados temas de salas reales, cámaras, animaciones, textos sobre fondos complejos, nombres con espacios ni otros idiomas. Las lecturas de acción no se analizan; por ejemplo, `All-in` no equivale automáticamente a una apuesta numérica.

Todavía no hay reconstrucción de manos, asociación de lecturas a una mano concreta, estadísticas, almacenamiento duradero ni estrategias. La próxima fase, **Game State Engine**, reunirá estas observaciones y las cartas en un estado de partida y comparará sus cambios.
