# Autonomous Quant Trader

Sistema autónomo de trading cuantitativo. El núcleo de decisión es **estadístico y determinista**;
la IA investiga y analiza, pero **nunca envía órdenes**. Toda orden atraviesa un **Risk Engine**
independiente y cubierto por tests.

> Métrica principal: *risk-adjusted out-of-sample expectancy*, no "cuánto ha ganado".
> **NO TRADE es una decisión válida.**

## Estado (iteración 1)

| Componente | Estado |
|---|---|
| Monorepo, CI, tests, `.env.example`, exclusión de secretos | ✅ |
| Market data: `MarketDataAdapter`, Parquet + DuckDB, CSV, generador sintético | ✅ |
| Feature Engine (retornos, vol, ATR, RSI, MACD, EMA/SMA, Bollinger, VWAP, gaps, geometría de velas, régimen) | ✅ |
| Strategy DSL declarativo + catálogo (momentum, mean reversion, breakout, trend following, velas) | ✅ |
| Backtester por arrays (entrada a la apertura siguiente, stops intrabar conservadores, costes) | ✅ |
| Statistical Engine: IS/OOS, walk-forward, purged CV, Wilson, Bayes (Beta-Binomial), Monte Carlo, BH-FDR, estabilidad de parámetros, régimen, Edge Score | ✅ |
| Position Sizing (riesgo por stop + Fractional Kelly) | ✅ |
| Risk Engine (APPROVE / REJECT / ADJUST_SIZE) + slider de agresividad con límites absolutos | ✅ |
| `BrokerAdapter` + `SimulatedBroker` | ✅ |
| `Trading212Broker` | ⏳ stub (iteración 2) |
| Esquema Supabase (`supabase/migrations`) con RLS y privilegios mínimos | ✅ aplicado en el proyecto «Autonomous trading» |
| **Trader en streaming** (Binance spot, PAPER): feed WebSocket, motor por eventos, libro en sombra + evidencia forward, Risk Engine, exchange paper realista | ✅ bloque 2 |
| SQLite local + **dashboard en localhost** (kill switch, pausa, agresividad) | ✅ bloque 2 |
| **Research Lab**: research programado, golden check, champion/challenger, meta-learning | ✅ bloque 3 |
| **Acciones de EE. UU.** (Alpaca en vivo, Yahoo/Alpaca para research y simulación) | ✅ bloque 3 |
| **Swing multi-timeframe** (1 h / 4 h, features entre valores, FDR global único) | ✅ bloque 4 |
| **Analista IA** (OpenAI): propone hipótesis en el DSL que el lab examina; nunca opera | ✅ bloque 4 |
| Dashboard desplegado, sincronización de hipótesis con Supabase | ⏳ ver [`docs/roadmap.md`](docs/roadmap.md) |

Estado detallado requisito por requisito: [`docs/prd-traceability.md`](docs/prd-traceability.md).

## Trader en streaming (local)

```bash
uv sync
uv run python -m services.trader run                     # top-10 USDC en vivo + dashboard + Research Lab
uv run python -m services.trader research                # un ciclo del Research Lab ahora
uv run python -m services.trader simulate --learn        # 72 h reales, aprendiendo sobre la marcha
uv run python -m services.trader simulate --market stocks --headless   # acciones de EE. UU.
uv run python -m services.trader run --market stocks     # acciones en vivo (claves Alpaca en .env)
```

Sólo PAPER. Detalles, flujo y límites en [`services/trader/README.md`](services/trader/README.md).

## Inicio rápido (research)

```bash
uv sync                      # instala dependencias (Python 3.11+)
make check                   # ruff + mypy + pytest con cobertura
uv run python -m services.research.cli run --symbol SPY --timeframe 1d --strategy momentum
uv run python -m services.research.cli list
```

Datos reales (Yahoo Finance, diario ajustado) y estudio completo con FDR global:

```bash
uv run python -m services.research.cli fetch --universe default --start 2005-01-01
uv run python -m services.research.cli study --universe tradable --strategies all
uv run python -m services.research.cli study --universe tradable --persist   # guarda en Supabase
```

Universos: `default`, `tradable` (invertible en Trading 212 desde la UE), `eur`, `proxies`, o una
lista `AAPL,SAN.MC`. Sin red, la CLI usa `--source synthetic` (determinista). Para datos propios:

```bash
# Parquet: data/parquet/<timeframe>/<SYMBOL>.parquet
uv run python -m services.research.cli run --source parquet --symbol SPY --strategy breakout
# CSV: <dir>/<SYMBOL>_<timeframe>.csv con columnas timestamp/date, open, high, low, close, volume
uv run python -m services.research.cli run --source csv --data-dir ./csv --symbol SPY
```

Cada ejecución escribe en `reports/` un JSON y un Markdown reproducibles (hash de datos, hash de
configuración de la estrategia, semilla, versión) con: tests de hipótesis múltiples, métricas
IS vs OOS, intervalos de confianza, posterior bayesiano, análisis de costes, walk-forward,
Monte Carlo, régimen, estabilidad de parámetros, Edge Score y veredicto
(`CHALLENGER_CANDIDATE` o `REJECTED`).

## Estructura

```
apps/dashboard/        dashboard local (local/); Lovable / Next.js → Vercel pendiente
services/research/     CLI del Research Engine
services/trader/       trader en streaming (PAPER) + API/WebSocket del dashboard local
services/ai_analyst/   Analista IA (sin acceso a órdenes) — pendiente
packages/aqt/
  common/      configuración (DEV/PAPER/LIVE, doble flag LIVE), tipos
  data/        adaptadores de datos, Parquet + DuckDB, datos sintéticos
  indicators/  indicadores causales
  features/    Feature Engine + patrones de velas
  regime/      clasificador tendencia × volatilidad
  strategies/  DSL + catálogo
  backtest/    motor + modelo de costes
  statistics/  validación estadística, Bayes, FDR, Monte Carlo, Edge Score
  sizing/      Position Sizing Engine
  risk/        Risk Engine, perfiles, límites absolutos
  brokers/     BrokerAdapter, SimulatedBroker, PaperExchange, Trading212 (stub)
  stream/      trader en streaming: feed, velas, features, estrategias, evidencia, SQLite
  research/    pipeline + informes
supabase/migrations/   esquema PostgreSQL + RLS
docs/                  PRD, arquitectura, roadmap
tests/
```

## Supabase

Aplica en orden los ficheros de `supabase/migrations/` (SQL Editor o MCP). Son atómicos y
re-ejecutables; el esquema inicial aborta sin crear nada si encuentra tablas ajenas con alguno de
nuestros nombres. `20261001010000_harden_privileges.sql` retira el acceso `anon`, deja al
dashboard sólo lectura + slider/kill switch y bloquea la llamada RPC a la función de auditoría.

## Seguridad

- Los secretos nunca están en el código ni en el frontend: `.env` está ignorado, CI ejecuta gitleaks.
- LIVE exige `TRADING_MODE=LIVE` **y** `LIVE_TRADING_ENABLED=true`; cualquier otra combinación falla.
- El dashboard puede mover el slider y el kill switch (auditado), pero no puede habilitar LIVE.
- El slider de agresividad nunca supera `AbsoluteLimits` (riesgo/trade ≤ 2 %, sin apalancamiento,
  sin cortos, sin margen).

Documentación: [PRD](docs/PRD.md) · [Trazabilidad](docs/prd-traceability.md) · [Arquitectura](docs/architecture.md) · [Roadmap](docs/roadmap.md)
