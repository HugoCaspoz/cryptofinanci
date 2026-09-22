# Fase 10 — Reconstrucción conservadora de acciones

Se generan `PLAYER_FOLDED`, `PLAYER_CHECKED`, `PLAYER_CALLED`, `PLAYER_BET`, `PLAYER_RAISED` y `PLAYER_ALL_IN` durante la captura. Se guardan en el mismo archivo transaccional de manos y se reproducen mediante el contrato de eventos existente. No hay recomendaciones estratégicas.

## Señales y alcance

El perfil **Zeros demo** reconoce, directamente en los píxeles de las seis regiones `players.*.action`, las etiquetas `ACTIVE`, `FOLD`, `CHECK`, `CALL`, `BET`, `RAISE` y `ALL-IN`. Compara máscaras con referencias visuales sintéticas, exige similitud mínima de 0,90 y margen de 0,08 sobre la segunda referencia. No ejecuta OCR para estas etiquetas. El layout ya incluía esas regiones: se pueden inspeccionar con el overlay existente.

Se requieren tres observaciones consecutivas de la misma etiqueta. Una zona vacía, oculta o desconocida rompe la confirmación; nunca equivale a check o fold. Un perfil distinto o una resolución incorrecta deshabilitan el reconocimiento de acciones. Estas referencias **no reconocen botones, etiquetas ni indicadores de salas reales**.

El motor combina ese reconocimiento con los filtros de importes existentes:

1. Confirma un único indicador visual de turno y obtiene un estado inicial con bote, apuestas y stacks conocidos, unidades iguales y evidencia reciente de los seis asientos.
2. Espera una etiqueta de acción estable del mismo asiento. No arma una acción al conectarse directamente a una etiqueta ya visible sin observar antes el turno.
3. Espera lecturas de importes confirmadas después de comenzar a observar esa etiqueta. Admite que OCR y etiqueta se confirmen en frames distintos.
4. Contrasta los cambios exactos mediante `Decimal`. Si otro asiento cambia de stack o apuesta en ese intervalo, omite la atribución porque no puede ordenar las acciones.
5. Emite una sola acción y consume el turno observado. Una etiqueta persistente no vuelve a emitirla; otra acción del mismo asiento necesita un nuevo ciclo de turno.

Las lecturas de importes deben tener como máximo 2,5 segundos de antigüedad. El turno armado caduca a los 12 segundos; al confirmar una etiqueta hay hasta seis segundos para corroborar los importes. Un salto de observación superior a 2,5 segundos invalida el turno pendiente. Los cambios de mano o calle también lo invalidan. Se conserva un único turno pendiente y seis filtros visuales de tamaño fijo.

## Reglas de inferencia

En todas las reglas hacen falta turno y etiqueta visual concordantes. Un cambio de OCR por sí solo no genera acciones.

| Acción | Corroboración adicional |
| --- | --- |
| Bet | Descenso del stack = incremento de apuesta = incremento del bote, todos positivos; la mayor apuesta inicial es cero. |
| Call | Misma igualdad de incrementos; apuesta final igual a la mayor apuesta inicial. |
| Raise | Misma igualdad; ya había una apuesta positiva y el total final la supera. |
| All-in | Misma igualdad y stack final cero, junto a etiqueta `ALL-IN`. |
| Check | Stack, apuesta y bote sin cambios; el asiento ya igualaba la mayor apuesta. |
| Fold | Stack, apuesta y bote sin cambios, tras turno y etiqueta `FOLD`. No se deduce de la desaparición de cartas. |

El ejemplo de `app.md` —stack 15000 → 14500, apuesta 0 → 500 y bote 1000 → 1500— produce `PLAYER_BET` con importe 500 cuando existen las señales visuales anteriores. Si falta alguna, se conserva la observación sin inventar una acción.

`amount` mantiene su significado del contrato de la fase 8: **apuesta total visible en la calle**, no incremento pagado. Por ejemplo, subir de 100 a 1000 pagando 900 se registra con `amount="1000"`. No se calculan tamaños mínimos legales de raise, side pots, devolución de apuestas, rake ni orden completo de acción.

Los flags `folded` y `all_in` permanecen durante la mano, incluidas las calles posteriores, y se reinician para la siguiente. `current_player` indica únicamente un turno visual confirmado en la observación actual. Los eventos incluyen asiento, mano, frame, tiempo de fuente, confianza y `action_evidence` con las cinco señales utilizadas. La confianza es un indicador de coincidencia, no una probabilidad calibrada ni una garantía de legalidad de la acción.

## Integración e interfaz

- `VisionObservation.actions` transporta observaciones visuales inmutables al motor de estado.
- `GameStateEngine` delimita primero la mano, aplica la reconstrucción y publica los eventos con su estado resultante.
- `CaptureEngine` guarda automáticamente las nuevas acciones con el lote de eventos del frame, utilizando la persistencia de la fase 9.
- `GET /api/capture` incorpora `observation_state.actions`: contador, estado del reconocimiento, asiento pendiente y motivo de espera/rechazo.
- `/live` muestra el contador de acciones, mensajes de evidencia insuficiente, turno observado y estados fold/all-in.
- `/hands/:id` muestra las acciones guardadas con asiento, importe total, confianza y señales. Los registros anteriores, sin `action_evidence`, siguen siendo legibles.

La interfaz continúa usando el sondeo HTTP de las fases anteriores. La reorganización del panel en directo y la distribución de eventos por WebSocket corresponden a la fase 11.

## Ejecutar y probar

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_action_video.py
```

En http://localhost:5173/live, con layout **Zeros demo**, reproduce `sample_data/actions-demo.avi`. El vídeo dura 56 segundos y empieza en flop, por lo que el inicio de la mano es parcial. Muestra check, bet 500, call 500, raise a 1000, fold y all-in 1000 en los seis asientos. El EOF conserva la mano como incompleta, con sus seis acciones guardadas. Abre «Manos» y recarga su detalle para comprobarlo.

Backend:

```powershell
docker compose build backend
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm zeros-backend-tests
```

La prueba opcional de PostgreSQL usa la base exclusiva `zeros_phase9_checks` creada en la fase anterior; nunca debe apuntar a la base de la aplicación:

```powershell
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Desde `frontend/`, con Compose en marcha, los **seis** vídeos de demo generados y sin otra captura activa:

```powershell
npm run build
npm run format:check
npm test
```

Las pruebas cubren las seis acciones, importes fraccionarios, apuesta total frente a incremento, incoherencias, OCR retrasado, confirmación visual, duplicados, cambio de mano/calle y regiones ocultas. La integración decodifica un vídeo MJPEG a un frame por segundo con Tesseract real y comprueba archivo/reproducción; el navegador reproduce la demo de cinco FPS y consulta el detalle guardado. La demo dibuja el cero del stack como `0.00` y el bote con mayor grosor para conservar legibilidad al comprimir, sin reducir los umbrales del motor.

## Archivos y límites

Validación del backend en Docker: **228 pruebas aprobadas**, incluidas Tesseract real y la base PostgreSQL de pruebas. Tras reforzar la demo, la prueba de integración ampliada a MJPEG y un FPS volvió a pasar. La compilación de producción TypeScript/Vite y la comprobación Prettier también han pasado.

Navegador Chromium contra Compose: **14 pruebas aprobadas**. Se verifican las seis acciones del vídeo, asiento, importe, señales, persistencia al recargar y estado incompleto al finalizar; también las funciones anteriores de manos, OCR, cartas, layouts, captura de archivo y pestaña. Las pruebas de apertura esperan la respuesta de la nueva fuente antes de consultar su captura. Revisadas visualmente las capturas del detalle en escritorio y móvil, sin desbordamiento horizontal.

Nuevo módulo `backend/app/action_engine/` con visión, inferencia y demo; integración en VisionEngine, GameStateEngine y eventos; generador `backend/scripts/create_action_video.py`; pruebas de motor e integración. Cambios en los paneles de estado/eventos y detalle de manos, escenario de navegador y versión 0.10.0.

La implementación prioriza omitir atribuciones dudosas. Puede perder acciones rápidas, indicadores no reconocidos, cambios agrupados o mesas que no actualicen el bote con cada contribución. Requiere datos de los seis asientos y no cubre asientos vacíos. No reconstruye una hand history completa cuando falta evidencia, ni resuelve reglas de apuesta, botes secundarios o ganancias. No se ha validado una sala real ni una sesión de ocho horas. La fase 11 abordará la vista en directo y sus actualizaciones por WebSocket.
