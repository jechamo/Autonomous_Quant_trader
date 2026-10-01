# Autonomous Quant Trader — PRD + arquitectura técnica + plan de implantación

## 1. Visión
Construir un sistema autónomo de trading cuantitativo capaz de gestionar inicialmente un capital
real limitado a **100 €**, sin aportaciones posteriores, cuya finalidad sea investigar
estrategias, medir estadísticamente su validez, controlar el riesgo, ejecutar operaciones
automáticamente y aprender de sus resultados.

El sistema **no** basará las operaciones directamente en decisiones generadas por un LLM. El
núcleo de decisión será cuantitativo, estadístico y determinista. La IA se usará como
investigador, analista, generador de hipótesis, revisor de operaciones, detector de anomalías,
sintetizador de conocimiento y generador de estrategias Challenger. La ejecución final siempre
atravesará un **Risk Engine** independiente.

## 2. Principios
Nunca operar porque "el gráfico parece bueno". Cada señal debe tener evidencia cuantificable:

```
Pattern: Bullish engulfing + RSI < 32 + volumen > 1,5× media + precio > EMA200
Market regime: Bull trend / medium volatility
Sample: 4.822 ocurrencias        Probabilidad positiva: 64,8 % (IC 62,9–66,7 %)
Ganancia media: +1,73 %          Pérdida media: -0,82 %
Expected Value: +0,68 %          Profit Factor: 1,91      Max DD histórico: -9,2 %
```

## 3. Conceptos
Cada oportunidad tiene: **P(win)**, **Expected Value**, **Statistical Confidence** y
**Regime Compatibility**, que se combinan en un **Edge Score**.

## 4. Porcentaje de aciertos ≠ rentabilidad
`EV = P(win)·AvgWin − P(loss)·AvgLoss − Fees − Spread − Slippage`. Sólo es candidata una
estrategia con EV positivo **fuera de muestra**.

## 5–6. Position sizing
Se calcula primero el capital máximo en riesgo. Ej.: 500 €, riesgo 1 % → 5 €; stop 4 % → 125 €;
stop 10 % → 50 €. Flujo: Edge → EV → Confidence → Volatility → Stop Distance → Fractional Kelly
→ Risk limits → Available Cash → Final Position. Kelly nunca a tamaño completo
(p. ej. Kelly 28 % × 0,25 = 7 %, límite 20 % → 7 %).

## 7. Slider de agresividad (0–100)
No es "% invertido". Modifica a la vez: riesgo/trade, exposición máx. por posición y cartera,
confianza mínima, drawdown máx., pérdida diaria máx., posiciones simultáneas, coeficiente Kelly y
reserva de caja. **Nunca** puede eliminar los límites absolutos.

## 8. NO TRADE es una decisión
Es válido estar 17 % invertido / 83 % en caja si no hay oportunidades atractivas.

## 9. Research Engine
Python: Polars/Pandas, NumPy, SciPy, Statsmodels, scikit-learn, Optuna, DuckDB, PyArrow/Parquet.
Backtesting: vectorbt o motor propio por arrays; framework sencillo como validación secundaria.
Histórico masivo en **Parquet + DuckDB**; Supabase para metadatos, estrategias, resultados,
experimentos, operaciones, versiones, métricas y configuración.

## 10. Catálogo de estrategias
Candlestick, trend following, momentum, mean reversion, breakouts, volatility, volume, relative
strength, pairs, cross-sectional, market regime, multi-factor, ML classifiers/regressors.
Después: sentiment, news, macro. **Excluido inicialmente:** HFT, opciones, futuros, margen,
apalancamiento, cortos, RL con dinero real.

## 11. Feature Engine
Retornos 1/3/5/10/20, volatilidad, ATR, RSI, MACD, distancias EMA/SMA, Bollinger, volumen
relativo, desviación VWAP, gap, momentum, aceleración, fuerza de tendencia, drawdown, breadth,
correlación, beta, fuerza relativa, régimen, geometría de velas (body_size, upper/lower shadow,
body/range, gap, close_position, volume_ratio) — para descubrir patrones sin nombre tradicional.

## 12. Statistical Engine
In-sample, out-of-sample, walk-forward, time-series CV, costes, slippage, Monte Carlo, régimen,
estabilidad de parámetros. Evitar look-ahead, survivorship, leakage, overfitting, selection bias
y data snooping. Control de **multiple hypothesis testing** (FDR).

## 13. Bayesian Evidence Engine
Distinguir 95/100 de 9.500/10.000: posteriors, intervalos creíbles, actualización bayesiana con
cada operación.

## 14. Champion / Challenger
La IA nunca despliega cambios directamente. Challenger: Backtest → OOS → Walk-forward → Costes →
Paper → Comparación con Champion → promoción auditada.

## 15. Shadow Portfolios
Real (Champion) + shadow (Champion, Challengers A/B/C, Buy & Hold, Cash).

## 16. Counterfactual Learning
Cada decisión guarda lo ocurrido y lo que habría ocurrido con la decisión contraria.

## 17. Risk Engine (sin LLM, determinista, con tests)
Riesgo máx./trade, exposición por posición y cartera, pérdida diaria, drawdown, pérdidas
consecutivas, liquidez mínima, spread máx., edge mínimo, slippage máx., datos obsoletos, órdenes
duplicadas, horario, salud API, reconciliación, kill switch. Si alguno falla: **TRADE REJECTED**.

## 18. Cost awareness
`expected gross edge − fees − FX − spread − slippage = expected net edge`. Si sólo funciona antes
de costes, se descarta.

## 19. AI Analyst
Nunca envía órdenes. Analiza operaciones, errores, cambios de régimen, anomalías, degradación,
hipótesis, Challengers, literatura, noticias, macro, lecciones. Salida estructurada
(p. ej. *Hypothesis #482 — Claim / Evidence / Suggested experiment*). El Research Engine la
confirma o rechaza.

## 20. Memoria (Supabase)
strategies, strategy_versions, signals, orders, fills, positions, portfolio_snapshots,
experiments, backtests, walk_forward_runs, paper_runs, lessons, hypotheses, trade_reviews,
risk_events, market_regimes, daily_metrics, AI_reviews, AI_hypotheses, configuration.

## 21–22. Arquitectura
Frontend Lovable/Next.js en Vercel · Supabase · Research/Trading/Risk en Python · Worker en
Railway · Parquet + DuckDB · GitHub · OpenAI API · `BrokerAdapter` (Trading212Adapter primero,
IBKRAdapter después). Lovable sólo para UI (dashboard, portfolio, analytics, explorer, research,
AI journal, riesgo, slider, kill switch, backtests, champion/challenger, histórico); nunca para el
núcleo. El frontend nunca posee las claves del broker.

## 23–24. Entorno de desarrollo
Monorepo: `apps/dashboard`, `services/{research,trader,ai_analyst}`,
`packages/{strategies,indicators,statistics,risk,brokers,common}`, `data/parquet`,
`supabase/migrations`, `tests`, `docs`, `infra`. VS Code + agente de desarrollo; el agente no es
el runtime.

## 25. Runtime
Servicio Python en Railway (workers persistentes + cron): market scanner, daily review,
research, AI review, reconciliación.

## 26–27. Broker
Inicial: **Trading 212 Invest + Public API** (España soportada, entornos Demo/Live, API key +
secret, restricción por IP, fraccionarias). API en beta → revalidar antes de Live.
Alternativa profesional: Interactive Brokers (más difícil de operar desatendido en cloud).

## 28. OpenAI
Facturación API independiente de ChatGPT. Proyecto propio con API key, presupuesto, límites y
logging. Modelo barato para análisis frecuentes, potente para research. Nunca por tick.

## 29. Cuentas
GitHub, Supabase, Railway, Trading 212 Invest, OpenAI Platform, Vercel, Lovable. Sin proveedor
caro de datos inicialmente: `MarketDataAdapter`.

## 30. Hoja de ruta
1. Repositorio (main, develop, CI, tests, exclusión de secretos, `.env.example`).
2. Supabase (Auth, Postgres, Vault, Storage, RLS, migrations) — sin dinero ni claves reales.
3. Research Engine — CLI `python research.py --symbol SPY --timeframe 1h --strategy momentum`
   con informe reproducible.
4. Strategy DSL (ENTRY: RSI<30 AND close>EMA200 AND volume_ratio>1.5; EXIT: ATR stop OR target
   OR max holding).
5. Statistical Validation Engine (OOS, WF, Bayes, MC, multiple testing, costes, régimen).
6. Risk Engine aislado (Portfolio, Signal, Market State, Strategy Evidence, Risk Profile →
   APPROVE / REJECT / ADJUST_SIZE).
7. Cuenta Demo Trading 212 (`demo.trading212.com/api/v0`), credenciales en el gestor de secretos.
8. BrokerAdapter: get_balance, get_positions, get_orders, place_order, cancel_order,
   get_instruments, health.
9. Paper Trader: Signal → Risk → Broker → Demo; registrar todo, también rechazos.
10. Shadow Engine.
11. AI Analyst (daily_trade_review, strategy_degradation_analysis, hypothesis_generator,
    anomaly_detection, weekly_research_review).
12. Autonomous Research Loop.
13. Dashboard (Overview, Portfolio, Trades, Signals, Research Lab, Strategy Explorer,
    Champion/Challengers, Risk, AI Journal, Lessons, Experiments, System Health, Settings).
14. Deploy (Vercel, Supabase, Railway).
15. Security: DEV/PAPER/LIVE con claves distintas; LIVE exige `TRADING_MODE=LIVE` y
    `LIVE_TRADING_ENABLED=true`; GLOBAL KILL SWITCH.
16. Go-live gate: evidencia OOS, EV positivo tras costes, drawdown en límite, estabilidad por
    régimen, paper consistente, sin errores de reconciliación, Risk Engine validado, kill switch
    y recuperación del broker probados. Sólo entonces: 100 €.

## 31. Primera configuración LIVE
100 €, sin margen/apalancamiento/opciones/futuros/cortos; pocas operaciones, sizing pequeño,
pocas posiciones, límites estrictos. Objetivo: demostrar autonomía **sin perder el control del
riesgo**.

## 32. Escalabilidad
Nada depende de que el capital sea 100 €; el sizing escala sin modificar estrategias.

## 33. Métrica principal
**Risk-adjusted out-of-sample expectancy.**

## 34. Objetivo final
MARKET DATA → RESEARCH → HYPOTHESIS → BACKTEST → STATISTICAL VALIDATION → CHALLENGER →
PAPER/SHADOW → RISK VALIDATION → CHAMPION → POSITION SIZING → TRADE → RESULT → POST-TRADE
ANALYSIS → LESSONS → NEW RESEARCH — un ciclo continuo de aprendizaje cuantitativo y controlado.
