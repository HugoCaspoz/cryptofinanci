Quiero desarrollar una aplicación de inteligencia artificial capaz de analizar una mesa de Texas Hold'em a partir de una fuente de vídeo EN DIRECTO.

La entrada puede ser:

* captura de una ventana
* captura de pantalla
* stream de OBS
* webcam/cámara apuntando a una mesa física
* archivo de vídeo reproducido como stream para desarrollo y testing

La aplicación debe procesar continuamente los frames, detectar lo que ocurre en la mesa y reconstruir las manos mientras suceden.

IMPORTANTE:

Existen dos modos diferentes.

MODE = LIVE_REAL_MONEY

En partidas reales con dinero:

* detectar la mesa en directo
* reconocer cartas
* reconocer stacks
* reconocer apuestas
* reconstruir acciones
* identificar posiciones
* calcular estadísticas de rivales
* guardar toda la información
* calcular métricas internamente

Pero NO mostrar recomendaciones accionables de fold/call/raise/bluff mientras la mano esté activa.

Las recomendaciones y el análisis estratégico deben mostrarse una vez terminada la mano o la sesión, según configuración.

MODE = TRAINING

Para mesas simuladas, entrenamiento, replay o play-money:

se pueden mostrar recomendaciones inmediatamente:

* Fold
* Check
* Call
* Bet
* Raise
* All-in

junto con:

* sizing recomendado
* equity
* pot odds
* EV aproximado
* estrategia baseline
* estrategia exploitativa
* posibles faroles
* explicación

La arquitectura debe mantener ambos modos completamente separados.

---

# OBJETIVO GENERAL

La aplicación debe funcionar aproximadamente así:

VIDEO / SCREEN CAPTURE
↓
FRAME PROCESSOR
↓
TABLE DETECTION
↓
CARD / STACK / BET / POT RECOGNITION
↓
GAME STATE ENGINE
↓
HAND RECONSTRUCTOR
↓
OPPONENT MODEL
↓
POKER ENGINE
↓
STRATEGY ENGINE
↓
UI

Todo debe actualizarse continuamente mientras llega el vídeo.

No quiero procesar primero el vídeo entero.

Quiero una arquitectura basada en eventos y estados.

Ejemplo:

frame recibido

↓

se detecta cambio

↓

se actualiza GameState

↓

se genera PokerEvent

Ejemplos:

HAND_STARTED
PLAYER_FOLDED
PLAYER_BET
PLAYER_CALL
PLAYER_RAISE
FLOP_DEALT
TURN_DEALT
RIVER_DEALT
HAND_FINISHED

---

# STACK

Frontend:

React
TypeScript
Vite

Backend:

Python
FastAPI

Computer vision:

OpenCV

Vídeo:

FFmpeg
OpenCV VideoCapture

WebSocket:

FastAPI WebSocket

Base de datos:

PostgreSQL

Procesamiento:

Python

En el futuro:

Redis
Celery
GPU inference

---

# ARQUITECTURA

Crear módulos separados:

capture_engine/

vision_engine/

table_detector/

card_detector/

ocr_engine/

game_state_engine/

hand_reconstructor/

poker_engine/

strategy_engine/

opponent_model/

tournament_engine/

event_engine/

analysis_engine/

llm_explainer/

websocket_engine/

No crear archivos gigantes.

Cada módulo debe tener responsabilidades claras.

---

# FASE 1 — BASE DEL PROYECTO

Crear:

frontend/
backend/

Frontend:

React + TypeScript + Vite

Backend:

FastAPI

Crear WebSocket:

/ws/live

Crear páginas:

/

Dashboard

/live

Live Analysis

/sessions

Sesiones anteriores

/session/:id

Análisis de una sesión

Crear Docker Compose.

Resultado esperado:

frontend y backend funcionando y comunicación WebSocket activa.

---

# FASE 2 — FUENTE DE VÍDEO EN DIRECTO

Crear CaptureEngine.

Debe aceptar diferentes fuentes.

Inicialmente:

1. archivo de vídeo tratado como stream
2. captura de una ventana/pantalla

Interfaz:

class VideoSource

Métodos:

start()
stop()
get_frame()

Implementaciones:

FileVideoSource

ScreenCaptureSource

Posteriormente:

OBSSource
CameraSource

Cada frame debe incluir:

frame_id
timestamp
image
fps

NO procesar obligatoriamente 60 FPS.

Permitir configurar:

capture_fps = 5

Por ejemplo:

analizar 5 frames por segundo.

Resultado esperado:

ver en el frontend el vídeo que está siendo procesado.

---

# FASE 3 — PIPELINE EN TIEMPO REAL

Crear un pipeline asincrónico.

VideoCapture
↓
FrameQueue
↓
FrameProcessor
↓
VisionEngine
↓
GameStateEngine

No bloquear la captura mientras se analiza un frame.

Utilizar colas.

Si el procesamiento va más lento que el vídeo:

descartar frames antiguos.

Siempre priorizar el estado más reciente.

Medir:

capture FPS
processing FPS
queue size
processing latency

Mostrarlo en modo debug.

Resultado esperado:

procesamiento continuo sin acumulación infinita de frames.

---

# FASE 4 — CONFIGURACIÓN DE LA MESA

Inicialmente soportar UNA sola plataforma y resolución.

Ejemplo:

1920x1080

Crear:

table_layouts/platform_1920x1080.json

Definir regiones:

hero_cards
board
pot
dealer_button
blinds

Player 1:
nickname
stack
bet
action

Player 2:
...

etc.

Crear overlay de debugging.

Mostrar rectángulos encima del vídeo indicando las regiones detectadas.

Resultado esperado:

podemos comprobar visualmente que todas las zonas están correctamente configuradas.

---

# FASE 5 — DETECCIÓN DE CARTAS EN DIRECTO

Reconocer continuamente:

Hero cards

Flop

Turn

River

Representación:

{
rank: "A",
suit: "spades",
confidence: 0.98
}

No emitir evento nuevo simplemente porque otro frame contiene la misma carta.

GameStateEngine debe saber:

antes:

[]

ahora:

["As", "Jh"]

por tanto:

HOLE_CARDS_DETECTED

Después:

board antes:

[]

board ahora:

["Js", "7c", "4d"]

evento:

FLOP_DEALT

Resultado esperado:

reconocimiento estable sin eventos duplicados.

---

# FASE 6 — OCR EN DIRECTO

Detectar:

player nickname

stack

bet

pot

blinds

Usar preprocessing:

crop
resize
grayscale
threshold
contrast

Mantener confidence.

No actualizar valores con una lectura de baja confianza inmediatamente.

Usar temporal smoothing.

Ejemplo:

frames:

12500
12500
125OO
12500

resultado:

12500

Resultado esperado:

valores numéricos estables incluso con errores ocasionales de OCR.

---

# FASE 7 — GAME STATE ENGINE

Esta será una de las partes más importantes.

Crear:

GameState

Ejemplo:

{
hand_id,
street,
pot,
board,
hero_cards,
players,
current_player,
button_position,
small_blind,
big_blind
}

PlayerState:

{
player_id,
nickname,
seat,
position,
stack,
current_bet,
folded,
all_in
}

El GameStateEngine recibe observaciones del VisionEngine.

Debe comparar:

previous_state

con

current_observation

y producir eventos.

---

# FASE 8 — EVENT ENGINE

Crear eventos estructurados.

Ejemplos:

HAND_STARTED

PLAYER_FOLDED

PLAYER_CHECKED

PLAYER_CALLED

PLAYER_BET

PLAYER_RAISED

PLAYER_ALL_IN

FLOP_DEALT

TURN_DEALT

RIVER_DEALT

HAND_FINISHED

Ejemplo:

{
type: "PLAYER_RAISED",
player: "Player4",
amount: 450,
timestamp: 312.45,
confidence: 0.94
}

Resultado esperado:

una partida puede reconstruirse utilizando exclusivamente el stream de eventos.

---

# FASE 9 — DETECCIÓN DE NUEVA MANO

Detectar automáticamente inicio y final de manos.

Señales posibles:

dealer button cambia

hero cards desaparecen

hero cards nuevas aparecen

board desaparece

pot vuelve a cero

stacks se actualizan

Generar:

HAND_FINISHED

seguido por:

HAND_STARTED

Guardar inmediatamente la mano anterior.

Resultado esperado:

puede ejecutarse durante horas separando automáticamente las manos.

---

# FASE 10 — RECONSTRUCCIÓN DE ACCIONES

Combinar:

stack changes

bet changes

pot changes

visual action labels

player active state

para inferir:

fold
check
call
bet
raise
all-in

No confiar exclusivamente en OCR.

Usar múltiples señales.

Ejemplo:

stack:

15000 → 14500

player bet:

0 → 500

pot:

1000 → 1500

inferencia:

PLAYER_BET 500

Resultado esperado:

crear una hand history mientras ocurre la partida.

---

# FASE 11 — LIVE UI

Crear página:

/live

Diseño aproximado:

VIDEO

mesa siendo analizada.

Panel lateral:

CURRENT HAND

Hero:
A♠ J♥

Board:
J♣ 7♠ 4♦

Pot:
12.5 BB

Hero stack:
38 BB

Street:
Flop

Debajo:

LIVE EVENTS

12:35:41 Player2 folds

12:35:43 Player4 raises 2.2 BB

12:35:45 Hero calls

12:35:52 Flop Jc 7s 4d

El frontend debe recibir actualizaciones mediante WebSocket.

---

# FASE 12 — MOTOR MATEMÁTICO

Crear PokerEngine.

Calcular continuamente:

pot size

effective stack

SPR

pot odds

required equity

approximate equity

ranges

Monte Carlo simulation

El motor recibe GameState.

NO debe leer directamente vídeo.

Vision:

Video → GameState

Poker:

GameState → Analysis

Mantener separación absoluta.

---

# FASE 13 — MOTOR PREFLOP

Crear rangos configurables.

Considerar:

position

effective stack

number players

raise size

previous actions

blinds

antes

Devolver StrategyResult.

Ejemplo:

{
action: "RAISE",
sizing_bb: 7.5,
confidence: 0.91
}

En LIVE_REAL_MONEY:

guardar internamente el resultado pero no mostrarlo mientras la mano está activa.

En TRAINING:

mostrarlo inmediatamente.

---

# FASE 14 — MOTOR POSTFLOP

Analizar:

hand strength

draws

equity

board texture

SPR

range advantage

nut advantage

position

bet sizing

Detectar:

flush draw

straight draw

gutshot

pair

two pair

set

etc.

Clasificar boards.

---

# FASE 15 — MODELO DE RIVALES

Actualizar estadísticas DESPUÉS DE CADA ACCIÓN.

Mantener:

VPIP

PFR

3Bet

Fold to 3Bet

CBet

Fold to CBet

WTSD

Aggression Factor

etc.

Ejemplo visual:

Player4

Hands: 73

VPIP 41%

PFR 13%

3Bet 2%

Fold to CBet 68%

Confidence:

MEDIUM

---

# FASE 16 — MODELO ADAPTATIVO DE RIVALES

OpponentModel debe modificar estimaciones de rango dependiendo de las acciones observadas.

Ejemplo:

Player4:

VPIP 42

PFR 10

3Bet 1

Probable preflop profile:

loose-passive

Pero nunca basar recomendaciones únicamente en etiquetas.

Usar estadísticas directamente.

A mayor número de manos:

mayor peso de las observaciones.

---

# FASE 17 — NIVEL DEL TORNEO

Añadir configuración:

buy-in

currency

tournament type

starting stack

players

prize structure

Buy-in puede utilizarse como prior inicial.

Ejemplo:

buy_in: €5

Pero:

observed_data > buy_in_prior

A medida que aumenten las manos observadas, reducir progresivamente el peso del prior.

---

# FASE 18 — STRATEGY ENGINE

Crear:

StrategyEngine

Debe combinar:

PokerEngine

OpponentModel

TournamentContext

GameState

y producir:

baseline_strategy

exploitative_strategy

Ejemplo:

baseline:

Call 62%
Raise 30%
Fold 8%

exploit:

Call 35%
Raise 61%
Fold 4%

En modo entrenamiento se puede mostrar en directo.

En partidas reales con dinero se almacena para revisión posterior.

---

# FASE 19 — DETECCIÓN DE FAROLES

Crear BluffAnalyzer.

Evaluar:

showdown value

blockers

unblockers

fold equity

range advantage

nut advantage

board texture

player tendencies

bet sizing

SPR

Devolver:

bluff_candidate

recommended_sizing

estimated_fold_frequency

blockers

reason

baseline_strategy

exploit_strategy

---

# FASE 20 — DETECCIÓN DE DECISION POINT

El sistema debe detectar cuándo Hero tiene que actuar.

Ejemplo:

evento:

HERO_DECISION_REQUIRED

GameState debe congelar un snapshot.

Guardar:

cards

board

pot

stacks

opponent ranges

actions

statistics

Esto permite posteriormente saber exactamente qué información había disponible en el momento de la decisión.

Muy importante:

NO utilizar acciones futuras para evaluar una decisión pasada.

Resultado esperado:

análisis temporalmente correcto.

---

# FASE 21 — EVALUACIÓN DESPUÉS DE LA DECISIÓN

Después de que Hero actúe:

comparar:

actual_action

strategy_result

Guardar:

Actual:

Fold

Baseline recommendation:

Call

Exploit recommendation:

Raise

Estimated EV difference:

-1.4 BB

Confidence:

74%

No mostrar falsa precisión.

---

# FASE 22 — FEEDBACK SEGÚN MODO

TRAINING:

puede mostrar en el momento:

Recommended action

Suggested sizing

Equity

Pot odds

Reasoning

LIVE_REAL_MONEY:

durante una mano activa mostrar únicamente información descriptiva como:

pot

stacks

board

event history

stats recopiladas

El análisis estratégico queda bloqueado.

Cuando corresponda según configuración:

HAND_FINISHED

o

SESSION_FINISHED

se desbloquea:

decision analysis

EV

alternative actions

bluff analysis

mistakes

---

# FASE 23 — TIMELINE DE DECISIONES

Mientras la sesión continúa construir:

HAND 51

Preflop ✅

Flop ⚠️

Turn ✅

River ❌

Al terminar la sesión:

click en una decisión

↓

mostrar frame exacto

↓

GameState de ese momento

↓

acción tomada

↓

alternativas

↓

análisis.

---

# FASE 24 — LLM EXPLAINER

El LLM NO decide cómo jugar.

Recibe resultados estructurados.

Ejemplo:

{
hero_hand,
board,
pot,
effective_stack,
actions,
ranges,
equity,
opponent_stats,
baseline_strategy,
exploit_strategy
}

Su única responsabilidad:

explicar.

Crear:

Simple mode

Advanced mode

---

# FASE 25 — LATENCIA

Medir:

capture latency

vision latency

state latency

analysis latency

total latency

Objetivos de ingeniería:

Vision processing:

< 200 ms

GameState update:

< 50 ms

UI update:

< 100 ms

No sacrificar estabilidad intentando conseguir latencia extrema demasiado pronto.

---

# FASE 26 — FRAME SAMPLING INTELIGENTE

No analizar todos los frames de la misma manera.

Estado normal:

2 FPS

Cuando detectamos cambios:

10 FPS temporalmente.

Ejemplo:

cambio en stack

cambio en pot

cambio de cartas

animación de acción

↓

burst mode durante 2 segundos.

Después volver a:

2 FPS.

Reducir considerablemente coste de procesamiento.

---

# FASE 27 — BUFFER TEMPORAL

Guardar un buffer circular de frames.

Ejemplo:

últimos 10 segundos.

Si detectamos un evento tarde:

podemos retroceder y localizar el frame exacto.

CircularBuffer:

10-30 segundos.

Esto será importante para reconstruir acciones correctamente.

---

# FASE 28 — CORRECCIÓN MANUAL

Permitir:

pause analysis

editar:

cards

stack

action

bet

player

board

Después:

resume

Las correcciones deben actualizar GameState sin romper la sesión.

Guardar correcciones como dataset.

---

# FASE 29 — SESIONES LARGAS

El sistema debe poder funcionar durante:

2h

4h

8h

sin crecimiento ilimitado de memoria.

No conservar todos los frames.

Guardar únicamente:

events

important frames

decision snapshots

hand boundaries

frames con errores

correcciones

---

# FASE 30 — DASHBOARD FINAL

Al finalizar sesión mostrar:

Hands observed

Hands played

VPIP

PFR

3Bet

Estimated EV lost

Biggest mistakes

Best decisions

Bluff opportunities missed

Bad bluff attempts

Opponent profiles

Top leaks

Mostrar:

TOP 10 MOST EXPENSIVE DECISIONS

Click:

↓

abrir mano

↓

mostrar frame correspondiente

↓

explicar decisión.

---

# REGLAS DE ARQUITECTURA

La visión nunca debe decidir estrategia.

vision_engine

solo observa.

game_state_engine

reconstruye la partida.

poker_engine

hace cálculos.

opponent_model

estima comportamiento/rangos.

strategy_engine

genera estrategia.

llm_explainer

explica.

---

# REGLA CRÍTICA

Nunca utilizar información futura para evaluar una decisión.

Para cada HeroDecision crear:

DecisionSnapshot.

Este objeto es inmutable.

Debe representar exclusivamente lo conocido hasta ese instante.

---

# FORMA DE DESARROLLO

Trabajar fase por fase.

Cuando diga:

"Empieza fase 1"

solo implementar fase 1.

Antes de pasar a siguiente fase:

ejecutar proyecto

ejecutar tests

comprobar errores

documentar cambios

Cuando diga:

"fase siguiente"

revisar primero la fase anterior.

No intentar construir todo desde el principio.

Priorizar una implementación funcional antes de optimizaciones.

Para cada fase terminar indicando:

1. Qué se ha construido.
2. Qué archivos se modificaron.
3. Cómo ejecutarlo.
4. Cómo probarlo.
5. Qué limitaciones tiene actualmente.
6. Qué abordará la siguiente fase.
