# Trader en streaming (PAPER, local)

Bot intradía de alta rotación sobre datos en tiempo real de **Binance spot**. Corre en tu
máquina, guarda todo en **SQLite** y sirve un dashboard en `http://127.0.0.1:8000`.

Menú de arranque: doble clic en `AQT.cmd` en la raíz del repo (o `uv run python -m
services.launcher`). Elige el modo con las flechas, rellena los campos (cada uno explica qué hace),
`F5` arranca, `F2` copia el comando y `Ctrl+C` lo para y vuelve al menú.

```bash
uv sync
uv run python -m services.trader run                               # top-10 USDC + Research Lab
uv run python -m services.trader run --symbols BTCUSDC,ETHUSDC,SOLUSDC --cash 100
uv run python -m services.trader replay                            # mismo motor sobre los ticks grabados
uv run python -m services.trader ticks                             # qué se ha grabado
```

> En redes con antivirus/proxy que re-firma HTTPS, `uv sync` necesita `UV_SYSTEM_CERTS=true`.
> El trader ya usa el almacén de certificados del sistema.

## Flujo

```
Binance WS (bookTicker + aggTrade) ─► velas de N s ─► features incrementales ─► estrategias
        │                                                                    │ intención (stop/objetivo)
        └─► SQLite (ticks)                       filtro de costes (objetivo ≥ 2× coste i/v)
                                                                             │
              ┌──────────────────────────────────────────────────────────────┤
              ▼                                                              ▼
   libro EN SOMBRA (todas las señales)                       libro PAPER (una posición/símbolo)
   → evidencia forward: Edge Score, BH-FDR ────────────────► Risk Engine (APPROVE/REJECT/ADJUST)
                                                                             ▼
                                                           PaperExchange (latencia, bid/ask, fees)
```

- **Mismo motor en vivo y en replay.** El reloj es el de los eventos: una vela sólo se decide
  cuando llega un evento posterior a su cierre y la orden se llena tras la latencia contra el
  libro de ese momento (compras al ask, ventas al bid). Sin look-ahead.
- **La evidencia se gana operando en sombra.** Al arrancar ninguna estrategia tiene evidencia,
  así que el Risk Engine rechaza todo lo que va a paper; las señales se operan virtualmente y, en
  cuanto una estrategia acumula operaciones netas de costes con Edge Score y confianza suficientes
  (corregidas por FDR), sus señales empiezan a pasar. Se persiste entre reinicios.
- **Costes primero.** Con 0,10 % por lado (Binance taker) el coste ida y vuelta ronda 0,3 % con
  slippage. Una señal cuyo objetivo no cubre 2× ese coste se descarta y se cuenta como
  *bloqueada por coste*: si ves muchas, el mercado no se está moviendo lo suficiente para pagar
  comisiones a ese horizonte. `--fee 0.00075` modela el descuento por pagar en BNB.
- **Guardas extra** (sólo más restrictivas que el Risk Engine): límite de órdenes por minuto,
  cooldown por símbolo, pausa, cerrar todo, y si el bucle del feed falla el motor se pausa.
- **Divisa.** Todos los símbolos deben cotizar en la misma divisa (EUR, USDC…). Cada divisa
  tiene su cuenta paper (`run_id = live-<DIVISA>`), que arrastra el P&L realizado entre sesiones.
  Los pares en EUR tienen poco volumen; los USDC/USDT son mucho más líquidos.

## Research Lab: aprendizaje continuo

```bash
uv run python -m services.trader research                     # un ciclo ahora (top-10 USDC, 365 días)
uv run python -m services.trader research --timeframes 1h,4h  # sólo swing
uv run python -m services.trader research --timeframes 1d     # sólo diario (5 años de historia)
uv run python -m services.trader analyst --dry-run            # qué leería el Analista IA
uv run python -m services.trader simulate --learn --headless  # el bucle completo sobre 72 h reales
```

- Cada 6 h (proceso aparte, el trading no se detiene) prueba miles de variantes a varias escalas:
  intradía (7 familias sobre los últimos 7 días de velas de 1 s), swing de 1 h / 4 h (entre
  valores, tendencia, ruptura y reversión a corto plazo sobre 365 días) y diario (además máximo
  de 52 semanas y cambio de mes, sobre 5 años), con validación fuera de muestra, walk-forward,
  Monte Carlo y **un único FDR global** para todas. Las supervivientes pasan una comprobación
  *golden* en el motor real. Por qué está cada regla (y por qué no está el patrón de las salidas
  a bolsa): [`docs/estudio-reglas.md`](../../docs/estudio-reglas.md).
- **Swing**: las reglas de ≥ 1 h mantienen la posición entre sesiones (en acciones no son
  *day trades*); las intradía siguen cerrando antes del cierre.
- **Analista IA** (opcional, `OPENAI_API_KEY` en `.env`): antes de cada ciclo lee lo que el lab ha
  aprendido y propone hasta 5 hipótesis nuevas en el DSL, que el lab examina con el mismo rigor.
  Nunca opera ni ve claves de broker. Modelo `OPENAI_MODEL_STRONG` (si no `_CHEAP`, si no
  `gpt-5-mini`); máximo 6 llamadas al día. `--no-analyst` lo desactiva.
- **Challenger**: opera sólo en sombra hasta ganar evidencia forward. **Champion**: su evidencia
  convence al Risk Engine y opera en paper. **Retirada**: deja de funcionar (o de dar señales).
- **Meta-learning**: cada hora, de las operaciones ganadoras y perdedoras de cada estrategia
  (también las 5 base) aprende cuándo conviene filtrar sus señales; si mejora fuera de muestra
  nace una versión filtrada que vuelve a empezar como challenger.
- Todo queda en SQLite (`rules`, `rule_events`, `lessons`, `research_runs`, `hypotheses`) y en
  el dashboard.

## Acciones de EE. UU. (`--market stocks`)

- `simulate` y `research` funcionan sin cuenta con datos de Yahoo (~7 días de velas de 1 min).
- `run` necesita claves **paper** gratuitas de Alpaca en `.env` (`ALPACA_API_KEY_ID`,
  `ALPACA_API_SECRET_KEY`): dan streaming IEX y años de historia para el lab (15 min, 1 h y 1 d).
- Reglas intradía: sin entradas en los últimos 15 min y todo cerrado 5 min antes de las 16:00 NY.
  Reglas swing (≥ 1 h): sólo entran con mercado abierto y pueden mantener la posición de un día
  para otro.
- Para dinero real en EE. UU.: la regla PDT limita a 3 *day trades* en 5 días a cuentas margin
  < 25.000 $, y en cuentas cash el dinero de una venta tarda T+1 en liquidarse. Los ETF de EE. UU.
  pueden no estar disponibles para clientes minoristas de la UE (PRIIPs).

## Panel «Aprendizaje»: el circuito y las bolas

Cada idea de regla viaja de izquierda a derecha. El número de cada nodo es cuántas han llegado
hasta ahí desde el primer ciclo; el nodo brilla más cuanto mayor es, y una pista se ilumina cuando
el nodo al que apunta tiene algo (`GET /api/learning`, cada 5 s).

| Nodo | Qué cuenta |
|---|---|
| IA | Ideas válidas del analista IA (antes de cada ciclo de research) |
| Ideas | Hipótesis examinadas: regla × parámetros × símbolo × escala de tiempo |
| Filtro | Sobreviven al filtro estadístico global (FDR) |
| Validación | Superan fuera de muestra, walk-forward, Monte Carlo, estabilidad y costes |
| Motor real | Ganan también en el motor real (latencia, bid/ask, comisiones) |
| En prueba | Llegaron a challenger: operan en sombra reuniendo evidencia |
| Opera | Llegaron a champion: operan en paper vía Risk Engine |
| ML | Filtros aprendidos (se enciende con el primer intento); vuelven como reglas en prueba |

Chispas: un ciclo de research recorre Ideas → Filtro → Validación → Motor real; una idea de la IA,
IA → Ideas; un cambio de estado, Motor real → En prueba → Opera; un intento de ML, En prueba ↔ ML;
una lección, Validación → Motor real; una operación en sombra llega a En prueba y una en paper a
Opera. Cada 2 s corre además una chispa decorativa por una pista encendida.

| Bola | Cómo se llena (0–100 %) | Puntitos |
|---|---|---|
| Reglas | La mejor regla en prueba: edge y confianza en vivo frente a los mínimos del Risk Engine; 100 % = champion | Una por regla; encendida = champion |
| Machine learning | Media de ejemplos reunidos / necesarios por estrategia (60, y +50 % tras cada intento fallido) | Una por estrategia; encendida = lista o con filtro |
| Camino a real | Media de los 10 criterios de la puerta a real (días/28, operaciones/50, …; los de sí/no valen 0 o 100 %) | Uno por criterio; encendido = cumplido |

## Puerta a real: ¿cuándo está listo?

El panel «Puerta a real» del dashboard evalúa cada hora 10 criterios sobre la cuenta paper
(≥ 28 días, ≥ 50 operaciones, neto positivo con ventaja estadística, ≥ 3 de 4 semanas positivas,
mejor que Buy & Hold, caída dentro del límite, órdenes por Alpaca paper sin descuadres y kill switch
probado). Cuando todos están en verde aparece un banner verde y, si pones
`NOTIFY_WEBHOOK_URL=https://ntfy.sh/<tu-tema>` en `.env` (app ntfy en el móvil), te llega un aviso.
Avisa también si deja de cumplirse. No activa nada: el paso a real lo decides tú.

## Límites deliberados

- Sólo **PAPER**. Con `TRADING_MODE=LIVE` el CLI se niega: no hay adaptador de órdenes reales.
- Sin cortos, sin margen, sin apalancamiento (`AbsoluteLimits`). El slider de agresividad nunca
  los supera.
- El dashboard sólo escucha en `127.0.0.1` y rechaza peticiones con `Origin` ajeno.
- Ningún LLM participa en la decisión.
