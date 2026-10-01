# Arquitectura

```
                 ┌──────────────────────────────┐
                 │ Dashboard (Lovable/Next.js)  │  Vercel — solo lectura + slider/kill switch
                 └──────────────┬───────────────┘
                                │ Supabase (Auth, Postgres + RLS)
┌───────────────────────────────┼─────────────────────────────────────────────┐
│ Railway workers (Python)      │                                             │
│                               ▼                                             │
│  Market data ─► Feature Engine ─► Strategy DSL ─► Backtest ─► Statistical   │
│  (Adapter,       (causal)          (declarativo)   (costes)    Validation    │
│   Parquet+DuckDB)                                              (OOS, WF, FDR, │
│                                                                 Bayes, MC)   │
│                                                                    │         │
│                                                    Challenger registry       │
│                                                                    │         │
│  Signal Engine ─► Position Sizing ─► RISK ENGINE ─► BrokerAdapter ─► Broker  │
│                   (stop + ¼ Kelly)   (determinista,  (Simulated /            │
│                                       sin LLM)        Trading212 / IBKR)     │
│                                                                              │
│  AI Analyst (OpenAI) ── lee resultados, escribe hipótesis/reviews ──┐        │
│      ✗ sin place_order  ✗ sin secretos del broker  ✗ sin escribir riesgo     │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Contratos clave

### Sin look-ahead
Cada feature en la fila `t` usa sólo información disponible al **cierre** de `t`
(`tests/test_indicators.py::test_features_have_no_look_ahead` lo verifica recortando el futuro).
El backtester ejecuta las entradas y salidas por señal en la **apertura de `t+1`**. Stops y
targets se evalúan intrabar; si ambos se tocan en la misma barra se asume el stop (conservador) y
los gaps a través del stop se ejecutan a la apertura.

### Costes
`CostModel`: comisión % y fija, spread (medio por lado), slippage y FX por lado. Con 100 € las
comisiones fijas dominan, por eso el coste se calcula sobre el nocional real. Los informes
muestran EV bruto, coste por operación y EV neto.

### Validación estadística
1. Barrido de la rejilla de parámetros **sólo en in-sample**.
2. p-valor unilateral (EV > 0) por variante y control **Benjamini–Hochberg** sobre todas.
3. Selección de la mejor variante IS → congelada → evaluada **una vez** en OOS.
4. **Walk-forward** anclado que re-selecciona en cada ventana.
5. Wilson CI, posterior Beta-Binomial, Monte Carlo de la secuencia de trades.
6. Desglose por régimen y estabilidad de parámetros (¿edge en la mayoría de vecinos o sólo en uno?).
7. Veredicto: `CHALLENGER_CANDIDATE` sólo si pasan todos los checks.

### Edge Score (0–100)
`100 × confianza × factor_muestra × compatibilidad_régimen × calidad_EV × P(EV>0)`;
es 0 si el EV neto ≤ 0.

### Position sizing
`nocional = min(equity × riesgo/trade ÷ distancia_stop, equity × Kelly × coef_fraccional)`,
después limitado por el Risk Engine (exposición por posición y cartera, reserva de caja,
participación en volumen). Escala con el capital sin tocar estrategias.

### Risk Engine
Entrada: `Portfolio`, `Signal`, `MarketState`, `StrategyEvidence`, `RiskProfile`.
Salida: `APPROVE | REJECT | ADJUST_SIZE` + todos los checks (para auditoría, incluidos rechazos).

Checks: kill switch, salud API, reconciliación, datos obsoletos, horario, órdenes duplicadas,
cotización válida, pérdida diaria, drawdown, pérdidas consecutivas, nº posiciones, spread,
slippage, liquidez, evidencia (edge score, confianza, EV neto tras costes en vivo), stop válido,
nocional mínimo y riesgo máximo por trade (defensa en profundidad). Las ventas que reducen una
posición existente se permiten aunque falle la evidencia; las ventas en corto se rechazan.

### Slider de agresividad
0–100 interpola simultáneamente: riesgo/trade, exposición máx. por posición y cartera, edge y
confianza mínimos, EV neto mínimo, drawdown y pérdida diaria máximos, nº posiciones, pérdidas
consecutivas, coeficiente Kelly, reserva de caja, spread y slippage máximos. El resultado se
recorta siempre a `AbsoluteLimits`; un `RiskProfile` construido a mano que los viole lanza error.

### Trader en streaming (`packages/aqt/stream`, `services/trader`)
Motor por eventos determinista que se usa igual en vivo (WebSocket de Binance) y en replay
(ticks grabados en SQLite). Reloj = eventos: la vela `[t, t+Δ)` se decide al llegar el primer
evento ≥ `t+Δ`, y la orden se llena tras la latencia contra el libro de ese momento.

- `bars` (velas por mid + flujo firmado de trades) → `features` (EMA, σ EWMA, z-score,
  desequilibrio de flujo y de libro, ruptura sobre máximos *previos*) → `strategies` (intención
  con stop/objetivo escalados por volatilidad).
- Filtro de costes en el motor: objetivo ≥ `min_cost_multiple` × (fees + spread + slippage).
- Dos libros: **sombra** (cada señal, virtual, mismo modelo de ejecución) → `EvidenceTracker`
  (Edge Score + BH-FDR sobre ventana móvil) y **paper** (Signal → `RiskEngine` → `PaperExchange`).
- Guardas del motor más restrictivas que el Risk Engine: órdenes/min, cooldown, pausa; las
  salidas (stop/objetivo en cada quote, tiempo y señal al cierre de vela) también pasan por él.
- `SQLiteStore`: ticks, decisiones con todos los checks, órdenes, operaciones, equity y controles.
- `services/trader/app.py`: FastAPI en 127.0.0.1 con WebSocket para el dashboard local.

### Research Lab (`packages/aqt/lab`, `services/trader/lab_scheduler.py`)
Aprendizaje continuo sin LLM, todo validado estadísticamente:

```
historia 1 s (Binance) / 1 min (Yahoo, Alpaca) ─► velas de research + flujo (taker / BVC)
   ─► run_study(INTRADAY_CATALOG): IS → BH-FDR → OOS → walk-forward → MC → FDR global
   ─► golden check en el StreamingEngine real ─► registro: candidate → CHALLENGER
   ─► sombra en vivo (evidencia forward) ─► review: CHAMPION (opera paper vía Risk Engine)
                                                    o RETIRED (+ lección)
   ─► meta-learning sobre sus operaciones (purged CV) ─► versión filtrada → CHALLENGER
```

- Un único lenguaje de reglas: el DSL que valida el research se ejecuta en vivo
  (`DslStreamStrategy`), reconstruyendo las velas de research desde las del motor; la paridad de
  señales está testeada. En replays las features causales se precalculan (equivalentes).
- El ciclo de research corre en un proceso aparte cada 6 h; revisión y meta-learning cada hora;
  la estrategia del motor se actualiza en caliente (`StreamingEngine.set_strategies`).
- Memoria en SQLite por mercado: `rules`, `rule_events`, `lessons`, `research_runs`; modelos ML
  versionados con hash de integridad.
- Acciones: sesión de EE. UU. (sin entradas en los últimos 15 min, cierre 5 min antes) y flujo
  estimado con Bulk Volume Classification tanto en research como en vivo.

### Datos
Histórico masivo en Parquet (`data/parquet/<tf>/<symbol>.parquet`) consultado con DuckDB.
Supabase guarda metadatos, estrategias, experimentos, señales, órdenes, métricas y configuración.
