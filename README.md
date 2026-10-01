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
| Paper Trader, Shadow Engine, AI Analyst, Dashboard | ⏳ ver [`docs/roadmap.md`](docs/roadmap.md) |

Estado detallado requisito por requisito: [`docs/prd-traceability.md`](docs/prd-traceability.md).

## Inicio rápido

```bash
uv sync                      # instala dependencias (Python 3.11+)
make check                   # ruff + mypy + pytest con cobertura
uv run python -m services.research.cli run --symbol SPY --timeframe 1d --strategy momentum
uv run python -m services.research.cli list
```

Sin datos reales, la CLI usa `--source synthetic` (determinista). Para datos propios:

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
apps/dashboard/        Frontend (Lovable / Next.js → Vercel) — pendiente
services/research/     CLI del Research Engine
services/trader/       Paper/Live trader — pendiente
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
  brokers/     BrokerAdapter, SimulatedBroker, Trading212 (stub)
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
