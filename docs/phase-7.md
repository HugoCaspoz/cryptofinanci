# Fase 7 — Game State Engine

Se integran las observaciones estabilizadas de cartas y OCR en `GameState` y `PlayerState`. El motor compara el estado anterior con el nuevo y publica cambios descriptivos, sin deducir acciones ni separar manos automáticamente.

## Estado y semántica

`GET /api/capture` añade `observation_state.game_state`. Se mantienen los contratos de cartas y OCR de las fases anteriores.

- `scope_id`: identificador de esta ejecución del motor; cambia al comenzar otra captura.
- `hand_id`: nulo hasta implementar la detección de manos en la fase 9.
- `street`: `unknown`, `preflop`, `flop`, `turn` o `river`, según las cartas confirmadas. Una captura que empieza en river puede informar river sin inventar las calles anteriores. Un board vacío por sí solo no prueba preflop: se requieren también cartas de Hero.
- `pot`, `small_blind`, `big_blind`: importes normalizados como cadenas decimales exactas o nulos. Las unidades se conservan en `pot_unit` y `blinds_unit`; nunca se convierten ni se asumen fichas.
- `board`, `hero_cards`: códigos como `As`, `Jh`, en arrays sin duplicados validados por el filtro de cartas.
- `players`: seis asientos, numerados del 1 al 6. Cada `PlayerState` contiene `player_id`, `seat`, `nickname`, `position`, `stack`, `stack_unit`, `current_bet`, `bet_unit`, `folded` y `all_in`.
- `current_player`, `button_position`, posiciones, folded y all-in permanecen nulos porque el detector no aporta esas señales. Un stack cero no se interpreta como all-in; una región vacía no significa fold.
- `revision`, `frame_id`, `timestamp`: número de cambios de valores y última observación procesada. El tiempo es relativo a la fuente, no la hora del servidor.
- `evidence`: estado, confianza, frame y tiempo de última confirmación y revisión de layout por campo. Sus claves de jugadores conservan el índice desde cero del OCR, por ejemplo `players.0.current_bet`.
- `events`: últimas 40 revisiones descriptivas en memoria.

Los identificadores de jugador son referencias a **asientos dentro de la captura**, no identidades duraderas de personas. Un cambio de nickname actualiza la lectura del asiento, sin inferir si ha cambiado su ocupante. El layout y las referencias siguen congelados por captura.

El estado agrupa lo último conocido: las regiones pueden haberse confirmado en tiempos distintos. No se presenta como una transacción de apuestas ni como una fotografía de todos los importes en el mismo instante. La evidencia permite detectar valores conservados durante lecturas dudosas; la UI muestra esa incertidumbre junto al dato. La calle procede de las últimas cartas confirmadas y puede quedar conservada cuando se pierde su lectura. Tampoco se borran importes por un cambio de calle: hacerlo podría inventar ceros o descartar observaciones válidas.

## Comparación temporal

`GameState` y sus jugadores son dataclasses congeladas con tuplas internas. `current_state` y `previous_state` solo contienen lo conocido al procesar su observación; no se alteran con frames posteriores. Los snapshots de la API son copias independientes, incluido su historial de cambios.

El motor conserva la estabilización anterior: tres lecturas de cartas y tres coincidencias entre cinco muestras OCR con confianza mínima del 80%. Rechaza identificadores de frame repetidos o decrecientes y tiempos negativos, no finitos o que no avanzan, antes de cambiar su estado. Un frame sin muestreo OCR no añade evidencia OCR.

Si cambian los valores confirmados, emite una única revisión que contiene todos los cambios detectados en esa observación:

```json
{
  "id": 2,
  "type": "GAME_STATE_UPDATED",
  "revision": 2,
  "frame_id": 6,
  "timestamp": 3.6,
  "changes": [
    {"field": "pot", "previous": "750", "current": "1500"},
    {"field": "players.0.stack", "previous": "12500", "current": "12000"},
    {"field": "players.0.current_bet", "previous": "0", "current": "500"}
  ]
}
```

Los frames idénticos, las nuevas puntuaciones de confianza y los cambios de calidad de lectura no generan revisiones de valores. La evidencia sí se actualiza. Cambiar una unidad con el mismo importe cuenta como cambio. Una revisión no afirma que los cambios tengan una misma causa ni que constituyan `PLAYER_BET`.

Los eventos de cartas existentes siguen en `observation_state.cards.events`; este historial de revisiones no vuelve a emitirlos como acciones de póker. No es todavía el Event Engine de la fase 8, ni un registro duradero que permita reconstruir toda una sesión. Solo se conservan dos estados del juego y 40 revisiones, además de los buffers limitados anteriores.

## Interfaz y archivos

El panel **Estado de la partida**, en `/live`, muestra calle, Hero, board, bote, ciegas y los seis asientos. Cada lectura muestra el momento de confirmación, y distingue los valores retenidos sin confirmación actual. **Cambios confirmados** muestra los valores anteriores y nuevos. Al detener la captura o perder conexión se indica que el estado puede estar desactualizado. El panel es descriptivo en ambos modos.

Nuevos archivos:

- `backend/app/game_state_engine/models.py`: contratos inmutables.
- `backend/app/game_state_engine/projection.py`: proyección y evidencia.
- `backend/app/game_state_engine/changes.py`: diferencias e historial limitado.
- `backend/tests/test_game_state.py`: pruebas deterministas.
- `frontend/src/game/types.ts`, `GameStatePanel.tsx` y `frontend/src/styles/game.css`.
- `frontend/public/fonts/`: DM Sans, Manrope y sus licencias OFL.

Se actualizan el motor y sus exports, API/handshake a fase 7, versión 0.7, contratos del frontend, Live, portada, progreso, pruebas OCR de integración/navegador, estilos, README y este documento. No se modifica `app.md`, ni se añaden dependencias Python o npm.

Durante la revisión previa, 140 pruebas de backend pasaron. Las pruebas de navegador encontraron bloqueos de carga en la petición externa a Google Fonts, confirmados en la traza de red. Se sirven ahora las mismas familias desde archivos locales, descargados del [repositorio oficial de Google Fonts](https://github.com/google/fonts), con sus licencias. La aplicación ya no necesita contactar con Google Fonts para cargar su tipografía.

La prueba de recuperación del layout se acota ahora a los avisos de su propio panel: al cargar pueden coincidir ese aviso y el aviso inicial de consulta de captura, por lo que buscar un único `role=alert` en toda la página era ambiguo.

## Ejecutar y probar

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_ocr_video.py
```

Abre http://localhost:5173/live y reproduce `sample_data/ocr-demo.avi`:

1. El estado confirma flop, Hero A♠ J♥, board J♠ 7♣ 4♦, bote 750 y ciegas 50/100.
2. Al ocultarse el bote y el stack del asiento 1, conserva sus valores y marca la lectura como no confirmada ahora. Esa ocultación no crea una revisión de valores.
3. Tras el segundo 8 confirma bote 1500, stack 12000 y apuesta 500. El historial muestra antes/después una sola vez por cambio confirmado.
4. Al finalizar queda un estado histórico. Una captura nueva reinicia valores, revisiones e identificadores de asientos.

Backend completo, incluido Tesseract real:

```powershell
docker compose build backend
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm zeros-backend-tests
```

Alternativa local sin Tesseract: `backend/.venv/Scripts/python -m pytest backend -q -p no:cacheprovider`; se omiten explícitamente las tres pruebas que requieren el ejecutable real. Las nuevas pruebas de estado cubren progresión de calles, entrada en river, importes/unidades, estabilidad, fallos y muestras omitidas, orden temporal, aislamiento de snapshots, reinicio e historial limitado.

Navegador, con los cuatro vídeos de prueba y servicios activos, desde `frontend/`:

```powershell
npm run build
npm run format:check
npm test
```

El escenario OCR también valida el estado integrado sobre vídeo real de prueba, los cambios sin duplicados, la incertidumbre durante la ocultación, el reinicio y las vistas de escritorio y móvil.

Resultado de validación:

- Backend en Docker: **155 pruebas aprobadas**, incluidas las tres que usan Tesseract real y las 15 nuevas del estado. Permanecen dos avisos de deprecación previos de Starlette/AnyIO.
- Backend en Windows sin Tesseract: **152 aprobadas y 3 omitidas** explícitamente.
- Navegador: **12 escenarios verificados**. La ejecución completa pasó 11; el restante detectó la ambigüedad del selector de avisos y pasó al repetirlo después de corregirlo. No fue necesario repetir los escenarios que ya habían pasado.
- Compilación TypeScript/Vite y formato correctos. Se revisaron visualmente los paneles de escritorio y móvil; en móvil la tabla tiene desplazamiento horizontal propio, sin desbordar la página.
- Frontend, backend y PostgreSQL saludables en Compose. Sin errores del pipeline ni respuestas 500 en los logs revisados.

## Límites y siguiente fase

Continúa pendiente la calibración y validación en una plataforma real. No hay detección de botón/turno, asociación de asientos a Hero, límites automáticos de mano, reconstrucción de acciones, persistencia o estrategia. El estado puede contener lecturas conservadas de momentos distintos, y no debe usarse como una mano ya reconstruida. Los datos llegan mediante el sondeo HTTP existente; el envío del estado por WebSocket se abordará en la fase de UI correspondiente.

La fase 8 implementará **Event Engine** y sus contratos de eventos de póker. La detección de manos y la inferencia de acciones conservan su orden en las fases 9 y 10.
