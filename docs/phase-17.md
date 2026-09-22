# Fase 17 — Contexto del torneo

## Qué se ha construido

`TournamentContext` recoge buy-in, moneda, tipo de torneo, stack inicial, participantes totales, jugadores restantes opcionales y estructura completa de premios. Se confirma junto con el inicio de la mano en «Modelo de rivales», mediante el endpoint existente `PUT /api/opponents/context`, campo opcional `tournament`. Omitirlo conserva el comportamiento de la fase 16.

El contexto es inmutable para esa mano y se almacena en el archivo privado del modelo de rivales. No se acepta una segunda configuración de la misma mano ni una solicitud con captura, mano o revisión obsoletas. Las modificaciones del formulario solo se aplican al confirmar otra mano. En entrenamiento, el resumen confirmado se recibe por HTTP/WebSocket y se recupera al recargar la página. Se pueden conservar los valores del formulario para preparar la próxima mano, pero siempre hay que confirmar su inicio de nuevo. Para observar otro torneo se debe iniciar una captura nueva: los perfiles se aíslan por captura, no por un nombre global del jugador.

## Datos y validación

| Campo | Significado y límites |
| --- | --- |
| `buy_in` | Coste de entrada declarado, de 0 a 1 000 000 000, máximo dos decimales. Cero permite freerolls. No se deducen comisiones ni aportaciones al bote de premios. |
| `currency` | Código de tres letras, normalizado a mayúsculas. El API valida la forma, no consulta un catálogo de divisas. La interfaz ofrece EUR, USD, GBP, CAD, AUD, CHF y JPY. No hay conversión de moneda. |
| `tournament_type` | `mtt`, `sit_and_go`, `satellite`, `bounty` u `other`. |
| `starting_stack` | Entero positivo en fichas, hasta 1 000 000 000. No sustituye al stack actual observado por OCR. |
| `players` | Total declarado de participantes, de 2 a 1 000 000; no es el número de asientos de la mesa. |
| `remaining_players` | Opcional; al menos 2, no mayor que el total y suficiente para los participantes confirmados en la mano. |
| `prize_structure` | `null` si se desconoce. Si se confirma, entre 1 y 1000 tramos, cada uno con primer puesto, último puesto y premio por jugador. |

Los tramos empiezan en el puesto 1, son contiguos, no se solapan, no superan el total de participantes y sus importes no aumentan en puestos posteriores. Los premios positivos usan `Decimal`, se serializan como cadenas y se suman sin errores de coma flotante. Los puestos con el mismo premio se pueden agrupar, incluidos premios iguales en satélites. Los bounties quedan fuera de esta tabla. Desconocer premios produce `prize_pool: null`, nunca un bote de premios cero inventado.

La suma no se fuerza a `buy_in × participantes`: puede haber comisiones, garantías u otras condiciones. No se calculan ICM, probabilidades de cobro, EV monetario ni recomendaciones derivadas de los premios.

## Prior opcional y peso de las observaciones

El buy-in por sí solo no genera un perfil de jugador. No se ha incorporado una tabla supuestamente empírica que equipare torneos baratos con rivales débiles. Opcionalmente, el usuario puede indicar una **hipótesis de población** para ese buy-in, moneda y formato, con nombre, VPIP, PFR, 3Bet y fuerza. Es un supuesto de estudio manual, no una estadística medida.

`population_prior` afecta únicamente a VPIP, PFR y 3Bet cuando la acción usa esa estadística. PFR no puede superar VPIP; 3Bet usa otro denominador y no tiene esa restricción. Las tasas se envían como fracciones entre 0 y 1; la interfaz las presenta como porcentajes. La fuerza equivale a entre 1 y 30 oportunidades anteriores, con valor inicial 10. El resto de estadísticas conserva los priors genéricos de la fase 16.

```text
tasa = (éxitos_observados + fuerza * tasa_prior_torneo) / (oportunidades + fuerza)
peso_datos = oportunidades / (oportunidades + fuerza)
peso_prior = fuerza / (oportunidades + fuerza)
```

Con fuerza 10, el prior pesa 100 % sin oportunidades, 50 % con 10 y aproximadamente 9.1 % con 100. Cuando hay más oportunidades que fuerza, los datos pesan más que el prior. Se cuenta la muestra de cada estadística, no todas las manos indiscriminadamente. Una 3Bet observada durante esta mano solo cambia el prior combinado de las manos siguientes: las muestras históricas se fijan al inicio para evitar usar información futura o contar dos veces la acción.

La evidencia de cada ajuste guarda `prior_source` (tipo, versión `explicit-population-v1`, nombre, buy-in, moneda y formato), `prior_strength`, `prior_weight` y `data_weight`. El panel muestra origen y peso del prior cuando interviene. El algoritmo de reponderación de combos sigue siendo `action-likelihood-v1`; cambian los supuestos de entrada, no el evaluador de cartas ni la fórmula de equity.

Ejemplo de `tournament` dentro del contexto de mano:

```json
{
  "buy_in": "5.00",
  "currency": "EUR",
  "tournament_type": "sit_and_go",
  "starting_stack": 10000,
  "players": 6,
  "remaining_players": 6,
  "prize_structure": [
    {"first_place": 1, "last_place": 1, "amount": "15.00"},
    {"first_place": 2, "last_place": 2, "amount": "9.00"},
    {"first_place": 3, "last_place": 3, "amount": "6.00"}
  ],
  "population_prior": {
    "label": "Estudio 5 EUR",
    "strength": 10,
    "vpip": 0.42,
    "pfr": 0.10,
    "three_bet": 0.01
  }
}
```

Estos porcentajes son un ejemplo de configuración, no datos de los jugadores de torneos de 5 EUR. Si se cambia el buy-in o el formato hay que revisar también la hipótesis; no se recalculan automáticamente sus tasas.

## Persistencia, modos y límites

La configuración confirmada se guarda en `context.tournament` del archivo de rivales. `adaptive.tournament` añade puestos pagados, suma de premios y política de prior. La persistencia usa el almacenamiento privado existente en SQLite/PostgreSQL, sin nueva migración. Los archivos antiguos sin torneo siguen siendo válidos. El archivo conserva el último contexto por captura; aún no es un historial de decisiones ni permite reanudar una mano después de reiniciar el backend.

En `TRAINING`, el contexto confirmado, sus resúmenes y ajustes son visibles. `LIVE_REAL_MONEY` mantiene el análisis interno y el archivo privado. La fase 17 no añade exposición del análisis por los endpoints públicos de manos, ni consejos postflop en directo.

El reconocimiento sigue calibrado para la mesa sintética Zeros. La configuración se introduce manualmente, no se extrae del lobby. No añade captura por cámara, tablas automáticas de nivel por buy-in, ICM, integración con una sala real ni una estrategia del torneo. Esa información queda disponible para el motor de estrategia de la fase 18.

## Ejecutar y probar

Desde la raíz del proyecto:

```powershell
docker compose up --build -d --wait
backend/.venv/Scripts/python backend/scripts/create_opponent_video.py
docker run --rm -d --name zeros-phase17-training -p 127.0.0.1:8001:8000 -e APP_MODE=TRAINING -e HAND_DB_PATH=/tmp/phase17-hands.sqlite3 zeros-backend
docker run --rm -d --name zeros-phase17-training-ui --link zeros-phase17-training:backend -p 127.0.0.1:5174:80 zeros-frontend
```

La instancia habitual está en http://localhost:5173/live. Para probar cálculos visibles abre http://localhost:5174/live:

1. Antes de reproducir la demo, activa «Añadir contexto de torneo a esta mano». Introduce buy-in 5 EUR, stack inicial 10000, seis participantes y seis restantes. Confirma premios de 15, 9 y 6 para los tres primeros puestos.
2. Activa el prior opcional, nómbralo «Estudio 5 EUR» y configura VPIP 42 %, PFR 10 %, 3Bet 1 %, fuerza 10.
3. Reproduce `sample_data/opponents-demo.avi`. Antes de los 18 s, selecciona solo los asientos 1 y 2, botón 1 y confirma el inicio. El resumen debe mostrar 30 EUR de premios.
4. Opcionalmente selecciona rangos adaptativos en «Motor matemático», Hero 1, rival 2 y bote que incluye apuestas.
5. Tras la 3Bet del asiento 2 a los 26 s, el rango mostrará el prior de torneo con tasa 1 % y peso 100 %: aún no había oportunidades anteriores. Su contador 3Bet 1/1 queda disponible para la próxima mano.
6. Al terminar, recarga la página: el contexto confirmado se recupera. Una nueva confirmación sobre la misma mano se rechaza; los datos no se reescriben retrospectivamente.

Backend completo, usando la base PostgreSQL exclusiva de pruebas `zeros_phase9_checks` ya creada:

```powershell
docker build -f backend/Dockerfile.test -t zeros-backend-tests backend
docker run --rm --network zeros_default -e HAND_TEST_POSTGRES=postgresql://zeros:zeros_local_dev@db:5432/zeros_phase9_checks zeros-backend-tests
```

Después, desde `frontend/`, sin solapar suites de vídeo:

```powershell
npm run build
npm run format:check
npm test
npm run test:training
```

Las pruebas específicas verifican importes exactos, premios desconocidos, tramos inválidos, moneda, límites, consistencia de participantes, priors sin valores no finitos, compatibilidad sin torneo, mayor peso de datos al crecer la muestra y aislamiento entre manos. Se amplían las pruebas de archivo SQLite/PostgreSQL y las políticas HTTP/WebSocket. El recorrido de entrenamiento cubre formulario móvil, torneo confirmado, acción OCR, evidencia del prior, archivo y recuperación tras recargar.

Para retirar las instancias auxiliares:

```powershell
docker stop zeros-phase17-training-ui zeros-phase17-training
```

## Archivos y siguiente fase

Validación realizada: **455 pruebas backend aprobadas**, con Tesseract y PostgreSQL exclusivo de pruebas; **20 pruebas de navegador aprobadas** (15 generales y 5 de entrenamiento), ejecutadas en secuencia. Compilación TypeScript/Vite y revisión Prettier correctas. Revisados el formulario en móvil y el panel completo en escritorio; sin desbordamiento horizontal. La demo comprobó el prior de torneo, su evidencia tras OCR, la persistencia y la recuperación del contexto al recargar. Persisten dos avisos de deprecación del cliente de pruebas, sin fallos.

Los servicios Compose quedaron saludables en fase 17, modo `LIVE_REAL_MONEY`, captura detenida, sin errores de captura o almacenamiento y con análisis públicos ocultos. Se retiraron los contenedores auxiliares de entrenamiento; pueden iniciarse de nuevo con los comandos de esta guía.

Nuevo `backend/app/tournament_context/` y `backend/tests/test_tournament_context.py`. Extendidos `opponent_model/models.py`, `opponent_model/adaptive.py`, las pruebas de servicio y los indicadores de API/WebSocket.

Nuevo `frontend/src/tournament/` con tipos, formulario y resumen. Cambios en panel y tipos de rivales, visualización de evidencia, estilos, versión y recorrido de entrenamiento. README y esta guía documentan la configuración y sus límites.

La fase 18 implementará el motor que combine estado, cálculo matemático, modelo de rivales y contexto de torneo para producir estrategia base y ajustes según lo observado.
