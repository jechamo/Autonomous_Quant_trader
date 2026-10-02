# Matriz de trazabilidad del PRD

Seguimiento requisito por requisito de [`docs/PRD.md`](PRD.md). Cada fila es un requisito atómico
con ID estable (`R<sección>.<nº>`), su estado, dónde está implementado, qué test lo cubre y qué
falta. `tests/test_traceability.py` verifica en CI que todas las rutas, símbolos y tests citados
existen y que el resumen cuadra con las filas.

**Leyenda:** ✅ hecho · 🟡 parcial · ⏳ pendiente · 🚫 excluido por diseño (y forzado en código)

**Última actualización:** 2026-10-02 · Prueba agrupada (panel) de las reglas diarias

<!-- summary:start -->
| Estado | Requisitos |
|---|---|
| ✅ | 218 |
| 🟡 | 33 |
| ⏳ | 37 |
| 🚫 | 7 |
| **Total** | **295** |

| Sección | ✅ | 🟡 | ⏳ | 🚫 | Total |
|---|---|---|---|---|---|
| §1 | 2 | 0 | 2 | 0 | 4 |
| §2 | 3 | 0 | 0 | 0 | 3 |
| §3 | 4 | 1 | 0 | 0 | 5 |
| §4 | 3 | 0 | 0 | 0 | 3 |
| §5 | 3 | 0 | 0 | 0 | 3 |
| §6 | 3 | 1 | 0 | 0 | 4 |
| §7 | 12 | 0 | 0 | 0 | 12 |
| §8 | 3 | 0 | 0 | 0 | 3 |
| §9 | 7 | 3 | 4 | 0 | 14 |
| §10 | 23 | 1 | 5 | 7 | 36 |
| §11 | 28 | 1 | 3 | 0 | 32 |
| §12 | 29 | 4 | 1 | 0 | 34 |
| §13 | 6 | 0 | 0 | 0 | 6 |
| §14 | 5 | 0 | 1 | 0 | 6 |
| §15 | 0 | 2 | 2 | 0 | 4 |
| §16 | 1 | 1 | 0 | 0 | 2 |
| §17 | 18 | 1 | 0 | 0 | 19 |
| §18 | 4 | 1 | 0 | 0 | 5 |
| §19 | 9 | 2 | 0 | 0 | 11 |
| §20 | 6 | 1 | 0 | 0 | 7 |
| §21 | 19 | 0 | 5 | 0 | 24 |
| §22 | 2 | 0 | 0 | 0 | 2 |
| §23 | 2 | 0 | 1 | 0 | 3 |
| §25 | 2 | 1 | 0 | 0 | 3 |
| §26 | 4 | 0 | 2 | 0 | 6 |
| §28 | 0 | 0 | 2 | 0 | 2 |
| §29 | 2 | 0 | 7 | 0 | 9 |
| §30 | 8 | 9 | 2 | 0 | 19 |
| §31 | 8 | 3 | 0 | 0 | 11 |
| §32 | 1 | 0 | 0 | 0 | 1 |
| §33 | 1 | 0 | 0 | 0 | 1 |
| §34 | 0 | 1 | 0 | 0 | 1 |
<!-- summary:end -->

---

## §1 Visión

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R1.01 | Núcleo de decisión cuantitativo, estadístico y determinista (no LLM) | ✅ | `packages/aqt/research/pipeline.py::run_research`, `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_research.py::test_pipeline_is_reproducible` | — |
| R1.02 | Toda ejecución atraviesa un Risk Engine independiente | ✅ | `packages/aqt/risk/engine.py::RiskEngine`, `packages/aqt/stream/engine.py::StreamingEngine` | `tests/test_stream.py::test_engine_paper_round_trip_through_risk_engine` | El trader en streaming encadena Signal → RiskEngine → broker (entradas y salidas); el futuro trader de Trading 212 debe reutilizar el mismo camino |
| R1.03 | Gestionar 100 € reales sin aportaciones | ⏳ | — | `tests/test_risk.py::test_small_account_100_eur` | Sizing y riesgo probados con 100 €; operar real depende del go-live gate (§30 paso 16) |
| R1.04 | IA como investigador/analista/generador de hipótesis/Challengers | ⏳ | `services/ai_analyst/README.md` | — | Iteración 3 |

## §2–3 Evidencia cuantificable y conceptos

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R2.01 | Cada señal con evidencia: muestra, P(win) e IC, ganancia/pérdida media, EV, PF, MDD | ✅ | `packages/aqt/statistics/metrics.py::compute_metrics`, `packages/aqt/statistics/confidence.py::wilson_interval` | `tests/test_statistics.py::test_metrics_basic` | Incluido en el informe de research |
| R2.02 | Evidencia ligada al régimen de mercado | ✅ | `packages/aqt/statistics/regimes.py::metrics_by_regime` | `tests/test_research.py::test_pipeline_is_reproducible` | — |
| R2.03 | Signal Engine en vivo que adjunte la evidencia a cada señal | ✅ | `packages/aqt/stream/engine.py::StreamingEngine`, `packages/aqt/stream/evidence.py::EvidenceTracker` | `tests/test_stream.py::test_engine_without_evidence_trades_only_in_shadow` | Cada señal en vivo lleva la `StrategyEvidence` forward de su estrategia; sin evidencia → REJECT |
| R3.01 | P(win) | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | Media posterior Beta-Binomial |
| R3.02 | Expected Value | ✅ | `packages/aqt/statistics/metrics.py::compute_metrics` | `tests/test_statistics.py::test_metrics_basic` | — |
| R3.03 | Statistical Confidence | ✅ | `packages/aqt/statistics/confidence.py::mean_return_test` | `tests/test_statistics.py::test_mean_return_test` | 1 − p-valor (ajustado por FDR en el pipeline) |
| R3.04 | Regime Compatibility | 🟡 | `packages/aqt/research/pipeline.py::_regime_compatibility` | `tests/test_research.py::test_pipeline_is_reproducible` | Heurística 0 / 0,5 / 1; mejorar con posterior por régimen |
| R3.05 | Edge Score que decide si hay ventaja suficiente | ✅ | `packages/aqt/statistics/edge.py::compute_edge_score` | `tests/test_statistics.py::test_edge_score` | — |

## §4 Win rate ≠ rentabilidad

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R4.01 | No usar sólo win rate | ✅ | `packages/aqt/statistics/metrics.py::compute_metrics` | `tests/test_statistics.py::test_win_rate_is_not_ev` | — |
| R4.02 | EV neto de fees, spread y slippage | ✅ | `packages/aqt/backtest/costs.py::CostModel`, `packages/aqt/backtest/engine.py::run_backtest` | `tests/test_backtest.py::test_costs_reduce_returns_and_equity_matches_trades` | — |
| R4.03 | Candidata sólo con EV positivo fuera de muestra | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_random_walk_is_not_promoted` | Check `oos_positive_ev_after_costs` del veredicto |

## §5–6 Position sizing

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R5.01 | Calcular primero el capital máximo en riesgo | ✅ | `packages/aqt/sizing/engine.py::PositionSizingEngine` | `tests/test_sizing.py::test_prd_examples` | — |
| R5.02 | Ejemplos PRD: stop 4 % → 125 €, stop 10 % → 50 € | ✅ | `packages/aqt/sizing/engine.py::PositionSizingEngine` | `tests/test_sizing.py::test_prd_examples` | — |
| R5.03 | Nunca "invertir siempre el X %" | ✅ | `packages/aqt/sizing/engine.py::PositionSizingEngine` | `tests/test_sizing.py::test_prd_examples` | — |
| R6.01 | Flujo Edge → EV → Confidence → Volatility → Stop → Kelly → límites → caja → posición | 🟡 | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_happy_path_approves` | Volatilidad entra vía stop ATR; la confianza filtra pero aún no escala el tamaño |
| R6.02 | Kelly nunca completo; Fractional Kelly configurable | ✅ | `packages/aqt/sizing/engine.py::kelly_fraction` | `tests/test_sizing.py::test_fractional_kelly_limits` | Coeficiente en `RiskProfile.kelly_coefficient`, máx. 0,5 |
| R6.03 | Límite del Risk Engine sobre la exposición candidata | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_adjust_size_when_position_cap_binds` | — |
| R6.04 | Sin ventaja → tamaño 0 | ✅ | `packages/aqt/sizing/engine.py::kelly_fraction` | `tests/test_sizing.py::test_no_edge_no_size` | — |

## §7 Slider de agresividad

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R7.01 | Slider 0–100 que no es "% invertido" | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_slider_is_monotonic_and_clamped` | `RiskProfile.from_aggressiveness` |
| R7.02 | Modifica riesgo por trade | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_slider_is_monotonic_and_clamped` | 0,25 % → 2 % |
| R7.03 | Modifica exposición máxima por posición | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_adjust_size_when_position_cap_binds` | 10 % → 35 % |
| R7.04 | Modifica exposición máxima de cartera | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_portfolio_exposure_cap` | 30 % → 90 % |
| R7.05 | Modifica confianza mínima de la señal | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_each_check_rejects` | 0,95 → 0,80 (y edge score 60 → 20) |
| R7.06 | Modifica drawdown máximo | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_each_check_rejects` | 8 % → 25 % |
| R7.07 | Modifica pérdida diaria máxima | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_each_check_rejects` | 1 % → 4 % |
| R7.08 | Modifica nº máximo de posiciones simultáneas | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_max_positions` | 2 → 8 |
| R7.09 | Modifica coeficiente Fractional Kelly | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_any_slider_value_respects_limits` | 0,10 → 0,50 |
| R7.10 | Modifica reserva de caja | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_cash_reserve_cap` | 50 % → 10 % |
| R7.11 | Nunca elimina los límites absolutos | ✅ | `packages/aqt/risk/profile.py::AbsoluteLimits` | `tests/test_risk.py::test_any_slider_value_respects_limits` | También un perfil manual que los viole lanza error |
| R7.12 | Slider editable desde el dashboard | ✅ | `services/trader/app.py::create_app`, `services/trader/runtime.py::TraderRuntime` | `tests/test_trader_service.py::test_api_state_control_and_persistence` | Dashboard local: el trader lo lee en caliente y lo persiste en SQLite. Versión Supabase/Lovable pendiente (R30.13) |

## §8 NO TRADE es una decisión

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R8.01 | El sistema no está obligado a invertir | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_random_walk_is_not_promoted` | — |
| R8.02 | Mantener caja si no hay oportunidades (reserva) | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_cash_reserve_cap` | Ver R7.10 |
| R8.03 | NO TRADE registrado como decisión | ✅ | `packages/aqt/stream/engine.py::StreamingEngine`, `packages/aqt/stream/store.py::SQLiteStore` | `tests/test_stream.py::test_cost_gate_blocks_moves_that_cannot_pay_fees` | Streaming: toda señal queda en `decisions` (APPROVE / REJECT / THROTTLED / PAUSED) y las bloqueadas por coste se cuentan por estrategia. `signals.decision` en Supabase pendiente |

## §9 Research Engine — stack

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R9.01 | Python | ✅ | `pyproject.toml` | — | 3.11+ |
| R9.02 | Pandas / NumPy / SciPy | ✅ | `pyproject.toml` | — | — |
| R9.03 | Polars | ⏳ | — | — | Se añadirá cuando haya volumen que lo justifique |
| R9.04 | Statsmodels | ⏳ | — | — | Previsto para tests de series temporales / regresiones |
| R9.05 | scikit-learn (ML) | ✅ | `packages/aqt/lab/meta.py::train_meta_filter` | `tests/test_meta.py::test_meta_filter_learns_a_real_pattern` | Gradient boosting para meta-labeling; validación con `purged_kfold_splits` |
| R9.06 | Optuna | ⏳ | — | — | Optimización con control de overfitting |
| R9.07 | DuckDB + PyArrow / Parquet | ✅ | `packages/aqt/data/store.py::ParquetStore` | `tests/test_data.py::test_parquet_roundtrip` | — |
| R9.08 | Backtester por arrays para investigación masiva | 🟡 | `packages/aqt/backtest/engine.py::run_backtest` | `tests/test_backtest.py::test_entry_next_open_and_stop_same_bar` | Bucle NumPy; falta acelerar (numba/vectorbt) para decenas de miles de variantes |
| R9.09 | Framework sencillo como validación secundaria | ⏳ | — | — | — |
| R9.10 | Histórico masivo en Parquet, no en Postgres | ✅ | `packages/aqt/data/store.py::ParquetStore` | `tests/test_data.py::test_parquet_roundtrip` | — |
| R9.11 | Supabase para metadatos, estrategias, resultados, experimentos | 🟡 | `packages/aqt/persistence/store.py::SupabaseStore` | `tests/test_persistence.py::test_persist_study_writes_expected_rows` | Código listo; falta primera escritura real (red + secreto `SUPABASE_SERVICE_ROLE_KEY`) |
| R9.12 | Descarga de datos históricos reales | 🟡 | `packages/aqt/data/yahoo.py::YahooAdapter`, `services/research/cli.py::fetch` | `tests/test_yahoo.py::test_adapter_retries_then_succeeds` | Yahoo/yfinance diario ajustado → Parquet. Probado con respuestas simuladas; la red del entorno aún bloquea Yahoo |
| R9.13 | Universo invertible en Trading 212 desde la UE (sin ETF de EE. UU. por PRIIPs/KID) | ✅ | `packages/aqt/data/universe.py::UNIVERSES` | `tests/test_yahoo.py::test_universe` | ETF de EE. UU. sólo como proxies de research (`EVIDENCE_ONLY`); prioridad a instrumentos en EUR |
| R9.14 | Estudio multi-símbolo × multi-estrategia desde CLI | ✅ | `services/research/cli.py::study`, `packages/aqt/research/study.py::run_study` | `tests/test_research.py::test_cli_fetch_and_study` | Informe de estudio JSON + Markdown con ranking |

## §10 Catálogo de estrategias

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R10.01 | Candlestick patterns | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | Familia `candlestick` en el research manual; el lab automático prueba `candle_reversal` (R10.31) |
| R10.02 | Trend following | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.03 | Momentum | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.04 | Mean reversion | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.05 | Breakouts | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.06 | Volatility | ✅ | `packages/aqt/strategies/intraday.py::INTRADAY_CATALOG` | `tests/test_dsl_stream.py::test_every_intraday_rule_renders_on_research_features` | Familia intradía `squeeze_breakout` (ATR bajo + ruptura con volumen); diario pendiente |
| R10.07 | Volume | ✅ | `packages/aqt/strategies/intraday.py::INTRADAY_CATALOG` | `tests/test_dsl_stream.py::test_every_intraday_rule_renders_on_research_features` | Flujo de órdenes (`flow_imbalance_*`) y `volume_ratio` en reglas intradía |
| R10.08 | Relative strength | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `relative_strength` (retorno a 20 barras frente a la mediana del universo) |
| R10.09 | Pairs | ⏳ | — | — | El panel multi-símbolo ya existe (R11.19); falta la familia de pares |
| R10.10 | Cross-sectional signals | ✅ | `packages/aqt/features/cross_section.py::cross_sectional_features`, `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_swing.py::test_cross_sectional_ranks_are_lagged_and_causal`, `tests/test_swing.py::test_multi_timeframe_cycle_finds_a_cross_sectional_leader` | Familias `xs_momentum`, `xs_momentum_long`, `xs_reversal`, `breadth_dip`; rangos retrasados una barra del panel |
| R10.11 | Market regime | ⏳ | `packages/aqt/regime/classifier.py::RegimeClassifier` | — | Features de régimen disponibles; falta familia que opere con ellas |
| R10.12 | Multi-factor | ⏳ | — | — | — |
| R10.13 | ML classifiers | ⏳ | — | — | — |
| R10.14 | ML regressors | ⏳ | — | — | — |
| R10.15 | Sentiment / news / macro (posterior) | 🟡 | `packages/aqt/news/book.py::news_features`, `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_news.py::test_cycle_finds_planted_news_drift_and_switches_news_off_without_a_source` | Noticias reales (Alpaca News) como features deterministas y 3 familias (R10.34–R10.36); sentimiento y macro pendientes. El sentimiento puntuado por un LLM no se backtestea (look-ahead del modelo) |
| R10.16 | Sin HFT | 🚫 | `packages/aqt/stream/engine.py::StreamingEngine` | `tests/test_stream.py::test_paper_fills_after_latency_at_the_far_side_with_fees` | Intradía en streaming (velas de segundos, horizontes de minutos) sí; HFT no: órdenes a mercado con latencia simulada, límite de órdenes/min y cooldown |
| R10.17 | Sin opciones ni futuros | 🚫 | `packages/aqt/brokers/base.py::Instrument` | — | Sólo acciones/ETF |
| R10.18 | Sin margen | 🚫 | `packages/aqt/risk/profile.py::AbsoluteLimits` | `tests/test_risk.py::test_property_approved_orders_never_exceed_limits` | `allow_margin=False`; nocional ≤ equity |
| R10.19 | Sin apalancamiento | 🚫 | `packages/aqt/risk/profile.py::AbsoluteLimits` | `tests/test_risk.py::test_manual_profile_cannot_breach_absolute_limits` | `max_portfolio_exposure ≤ 1.0` |
| R10.20 | Sin short selling | 🚫 | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_sell_exits_allowed_shorts_forbidden` | Además backtester long-only y `SimulatedBroker` rechaza cortos |
| R10.21 | Sin Reinforcement Learning con dinero real | 🚫 | — | — | No existe ningún componente RL |
| R10.22 | Sin decisiones directas de LLM | 🚫 | `packages/aqt/analyst/hypotheses.py::run_analyst` | `tests/test_analyst.py::test_analyst_package_cannot_import_brokers_risk_or_the_engine` | El único cliente LLM vive en `packages/aqt/analyst`, que no importa brokers, riesgo, motor ni servicios (test AST + `sys.modules`); sólo propone hipótesis que el lab examina |
| R10.23 | Estrategias intradía de alta rotación en streaming (momentum de flujo de órdenes, reversión) a varios horizontes | ✅ | `packages/aqt/stream/strategies.py::default_stream_strategies` | `tests/test_stream.py::test_momentum_entry_and_cost_gate` | Petición del usuario (2026-10-01): bot rápido y dinámico. Horizontes 1–20 min; FDR entre todas |
| R10.24 | Catálogo intradía para el Research Lab (7 familias, cientos de variantes) | ✅ | `packages/aqt/strategies/intraday.py::INTRADAY_CATALOG` | `tests/test_dsl_stream.py::test_every_intraday_rule_renders_on_research_features` | Mismo DSL que el research diario; objetivos amplios para que la búsqueda encuentre horizontes que paguen comisiones |
| R10.25 | Catálogo swing (≥ 1 h) con familias de base académica | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | 7 familias (~72 variantes): momentum y reversión entre valores, fuerza relativa, tendencia, ruptura con volumen, amplitud |
| R10.26 | Hipótesis del Analista IA como familia examinada por el lab | ✅ | `packages/aqt/lab/cycle.py::run_research_cycle` | `tests/test_analyst.py::test_cycle_tests_pending_ai_hypotheses_in_the_global_fdr` | Familia `ai_*`; mismas pruebas (OOS, walk-forward, Monte Carlo, golden check) y el mismo FDR |
| R10.27 | Estudio de reglas documentadas: qué probar, qué no y por qué | ✅ | `docs/estudio-reglas.md` | — | Petición del usuario (2026-10-02). Niveles A (efecto publicado aplicado como en el estudio), B (aplicado fuera de sus condiciones), C (sin respaldo académico o evidencia negativa) y D (descartada: IPO, pre-FOMC, momentum nocturno, sentimiento LLM en backtest). Auditoría de fuentes de todas las familias del sistema (§ 6) |
| R10.28 | Reversión tras N cierres a la baja seguidos | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_swing.py::test_documented_rules_fire_on_their_textbook_setups`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `streak_reversion` (1h/4h/1d): `down_streak ≥ n` sobre SMA200, sale con RSI(2) > 70. Nivel C: ejemplo del usuario sin respaldo académico; heurística de Connors y Alvarez 2009 |
| R10.29 | Reversión RSI(2) | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_swing.py::test_documented_rules_fire_on_their_textbook_setups`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `rsi2_reversion` (1h/4h/1d). Nivel C: sólo practicantes (Connors y Alvarez 2009) |
| R10.30 | Reversión IBS (cierre en mínimos del rango) | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_swing.py::test_documented_rules_fire_on_their_textbook_setups`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `ibs_reversion` sólo en 1d (`DAILY_ONLY`) sobre `close_position`. Pagonidis 2014: ETFs de índices, diario |
| R10.31 | Patrones de velas con contexto en el lab automático | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `candle_reversal` (envolvente o martillo + RSI bajo + EMA200); evidencia débil tras costes, se mide igualmente (nivel C) |
| R10.32 | Cerca del máximo de 52 semanas | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG`, `packages/aqt/strategies/swing.py::swing_families_for` | `tests/test_swing.py::test_documented_rules_fire_on_their_textbook_setups`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features`, `tests/test_swing.py::test_catalog_for_keeps_daily_and_equity_effects_where_documented` | Familia `near_52w_high`, sólo en 1d, mantiene 60 o 126 sesiones. George y Hwang 2004 (larga-corta, 6–12 meses); sólo la pata larga (nivel B) |
| R10.33 | Efecto cambio de mes | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG`, `packages/aqt/strategies/swing.py::swing_families_for` | `tests/test_swing.py::test_documented_rules_fire_on_their_textbook_setups`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features`, `tests/test_swing.py::test_catalog_for_keeps_daily_and_equity_effects_where_documented` | Familia `turn_of_month`, sólo 1d y acciones; días naturales (festivos pendientes). Ariel 1987; Lakonishok y Smidt 1988 |
| R10.34 | Deriva tras subida fuerte con noticias anómalas | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_news.py::test_cycle_finds_planted_news_drift_and_switches_news_off_without_a_source`, `tests/test_news.py::test_news_families_only_with_news`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `news_drift` (acciones con fuente de noticias): `news_ratio > k`, `ret_1 > 2 %`, volumen > 1,5×. Nivel C: Chan 2003 es mensual y su deriva fuerte es tras malas noticias |
| R10.35 | Rebote tras caída fuerte sin noticias | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_news.py::test_news_families_only_with_news`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `quiet_drop_reversal`: caída sin más noticias de lo normal, sobre SMA200. Chan 2003 (horizonte mensual; aquí días/horas, nivel B) |
| R10.36 | Deriva tras resultados (PEAD aproximado) | ✅ | `packages/aqt/strategies/swing.py::SWING_CATALOG` | `tests/test_news.py::test_news_families_only_with_news`, `tests/test_swing.py::test_swing_catalog_renders_on_augmented_features` | Familia `earnings_gap_drift`: titular de resultados + gap al alza + volumen > 2×. Sin datos de consenso (reacción del precio como sorpresa, Brandt et al. 2008). Bernard y Thomas 1989 |

## §11 Feature Engine

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R11.01 | Retornos 1/3/5/10/20 | ✅ | `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_indicators.py::test_feature_engine_columns` | — |
| R11.02 | Volatilidad rolling | ✅ | `packages/aqt/indicators/core.py::rolling_volatility` | `tests/test_indicators.py::test_feature_engine_columns` | — |
| R11.03 | ATR | ✅ | `packages/aqt/indicators/core.py::atr` | `tests/test_indicators.py::test_atr_positive` | — |
| R11.04 | RSI | ✅ | `packages/aqt/indicators/core.py::rsi` | `tests/test_indicators.py::test_rsi_bounds_and_extremes` | — |
| R11.05 | MACD | ✅ | `packages/aqt/indicators/core.py::macd` | `tests/test_indicators.py::test_feature_engine_columns` | — |
| R11.06 | Distancias EMA / SMA | ✅ | `packages/aqt/indicators/core.py::distance_to` | `tests/test_indicators.py::test_feature_engine_columns` | 20/50/200 |
| R11.07 | Posición en Bollinger | ✅ | `packages/aqt/indicators/core.py::bollinger_position` | `tests/test_indicators.py::test_bollinger_and_trend` | — |
| R11.08 | Volumen relativo a la media | ✅ | `packages/aqt/indicators/core.py::volume_ratio` | `tests/test_indicators.py::test_feature_engine_columns` | Media de las barras previas |
| R11.09 | Desviación VWAP | ✅ | `packages/aqt/indicators/core.py::vwap_deviation` | `tests/test_indicators.py::test_feature_engine_columns` | VWAP rolling (no intradía anclado) |
| R11.10 | Gap | ✅ | `packages/aqt/indicators/core.py::gap` | `tests/test_indicators.py::test_feature_engine_columns` | — |
| R11.11 | Momentum | ✅ | `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_indicators.py::test_feature_engine_columns` | `momentum_20` |
| R11.12 | Aceleración | ✅ | `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_indicators.py::test_feature_engine_columns` | — |
| R11.13 | Fuerza de tendencia | ✅ | `packages/aqt/indicators/core.py::trend_strength` | `tests/test_indicators.py::test_bollinger_and_trend` | t-stat de la pendiente |
| R11.14 | Drawdown | ✅ | `packages/aqt/indicators/core.py::rolling_drawdown` | `tests/test_indicators.py::test_feature_engine_columns` | — |
| R11.15 | Market breadth | ✅ | `packages/aqt/features/cross_section.py::cross_sectional_features` | `tests/test_swing.py::test_cross_sectional_ranks_are_lagged_and_causal` | `xs_breadth`: % del universo sobre su EMA-50, retrasado una barra |
| R11.16 | Correlación | ⏳ | — | — | Panel multi-símbolo disponible (R11.19); falta benchmark |
| R11.17 | Beta | ⏳ | — | — | Panel multi-símbolo disponible (R11.19); falta benchmark |
| R11.18 | Relative strength | 🟡 | `packages/aqt/features/cross_section.py::cross_sectional_features` | `tests/test_swing.py::test_cross_sectional_ranks_are_lagged_and_causal` | `xs_rel_ret_20` frente a la mediana del universo y `xs_rank_ret_*`; frente a un índice benchmark pendiente |
| R11.19 | Soporte multi-símbolo / benchmark en el Feature Engine | ✅ | `packages/aqt/features/cross_section.py::augment`, `packages/aqt/stream/dsl_strategy.py::ResearchBarBook` | `tests/test_swing.py::test_calendar_features_and_passthrough`, `tests/test_swing.py::test_live_cross_sectional_rule_matches_research` | El `FeatureEngine` deja pasar `xs_*` y calendario; en vivo el panel se recalcula con todas las series del timeframe |
| R11.20 | Régimen de mercado como feature | ✅ | `packages/aqt/regime/classifier.py::RegimeClassifier` | `tests/test_indicators.py::test_feature_engine_columns` | tendencia × volatilidad |
| R11.21 | Geometría de velas (body, sombras, body/range, close_position) | ✅ | `packages/aqt/indicators/core.py::candle_geometry` | `tests/test_indicators.py::test_candle_geometry_ranges` | — |
| R11.22 | Patrones con nombre derivados de la geometría | ✅ | `packages/aqt/features/engine.py::candlestick_patterns` | `tests/test_dsl.py::test_catalog_renders_on_features` | engulfing, hammer, shooting star, doji |
| R11.23 | Descubrimiento de patrones sin nombre tradicional | ⏳ | — | — | Geometría disponible; falta búsqueda automática (R30.12) |
| R11.24 | Features causales (sin look-ahead) | ✅ | `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_indicators.py::test_features_have_no_look_ahead` | — |
| R11.25 | Desequilibrio de flujo de órdenes (taker buy) como feature | ✅ | `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_dsl_stream.py::test_flow_features_are_causal` | `flow_imbalance_5/15` cuando hay `taker_buy_volume` (Binance) |
| R11.26 | Flujo estimado para acciones (Bulk Volume Classification) | ✅ | `packages/aqt/stream/stocks.py::bvc_taker_buy` | `tests/test_stocks.py::test_bvc_flow_estimate` | Misma estimación en research y en vivo (`ResearchBarBook(bvc=True)`) |
| R11.27 | Features de calendario (hora, día, minutos al cierre) | ✅ | `packages/aqt/features/cross_section.py::calendar_features` | `tests/test_swing.py::test_calendar_features_and_passthrough` | `minutes_to_close` sólo en acciones (sesión de NY) |
| R11.28 | Rachas de cierres a la baja / al alza | ✅ | `packages/aqt/indicators/core.py::streaks`, `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_indicators.py::test_streaks_count_consecutive_lower_and_higher_closes`, `tests/test_indicators.py::test_features_have_no_look_ahead` | `down_streak`, `up_streak`; un cierre igual reinicia la racha |
| R11.29 | RSI(2) y distancia al máximo de 252 barras | ✅ | `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_indicators.py::test_short_term_and_52_week_features` | `rsi_2`, `dist_high_252` (≤ 0) |
| R11.30 | Calendario mensual (día del mes, días a fin de mes) | ✅ | `packages/aqt/features/cross_section.py::calendar_features` | `tests/test_swing.py::test_month_calendar_uses_each_bars_own_trading_day` | `day_of_month`, `days_to_month_end`; fecha del último instante de la vela (NY en acciones), lo que corrige `day_of_week` en barras diarias de acciones |
| R11.31 | Features de noticias causales y honestas con la cobertura | ✅ | `packages/aqt/news/book.py::news_features`, `packages/aqt/news/book.py::NewsBook`, `packages/aqt/features/cross_section.py::augment` | `tests/test_news.py::test_news_features_are_causal_and_never_read_missing_coverage_as_quiet` | `news_1d`, `news_ratio` (intensidad frente a la media de 20 días), `news_earnings_1d`; sólo titulares publicados ≥ 5 min antes del cierre de la vela; NaN sin cobertura (nunca «sin noticias» por falta de datos); se ignoran resúmenes de más de 5 valores |
| R11.32 | Clasificación determinista de titulares | ✅ | `packages/aqt/news/classify.py::classify_headline` | `tests/test_news.py::test_parse_alpaca_news_and_classify_headlines` | Palabras clave (resultados, previsiones, ratings, M&A, FDA, legal, macro, IPO); reproducible y backtesteable, a diferencia de un LLM |

## §12 Statistical Engine

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R12.01 | In-sample analysis | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | — |
| R12.02 | Out-of-sample | ✅ | `packages/aqt/statistics/validation.py::split_in_out_of_sample` | `tests/test_statistics.py::test_split_and_walk_forward` | OOS = bloque más reciente |
| R12.03 | Walk-forward | ✅ | `packages/aqt/statistics/validation.py::walk_forward` | `tests/test_statistics.py::test_split_and_walk_forward` | Anclado o rolling |
| R12.04 | Time-series cross-validation | 🟡 | `packages/aqt/statistics/validation.py::purged_kfold_splits` | `tests/test_statistics.py::test_purged_kfold` | Splits implementados; no se usan aún en el pipeline |
| R12.05 | Simulación de costes | ✅ | `packages/aqt/backtest/costs.py::CostModel` | `tests/test_backtest.py::test_cost_model_validation` | — |
| R12.06 | Simulación de slippage | ✅ | `packages/aqt/backtest/costs.py::CostModel` | `tests/test_backtest.py::test_costs_reduce_returns_and_equity_matches_trades` | Fijo por lado; falta modelo dependiente de volatilidad/volumen |
| R12.07 | Monte Carlo | ✅ | `packages/aqt/statistics/montecarlo.py::monte_carlo_trades` | `tests/test_statistics.py::test_monte_carlo` | Bootstrap de trades |
| R12.08 | Análisis por régimen | ✅ | `packages/aqt/statistics/regimes.py::metrics_by_regime` | `tests/test_research.py::test_pipeline_is_reproducible` | — |
| R12.09 | Estabilidad de parámetros | ✅ | `packages/aqt/statistics/validation.py::parameter_stability` | `tests/test_statistics.py::test_parameter_stability` | — |
| R12.10 | Evitar look-ahead bias | ✅ | `packages/aqt/backtest/engine.py::run_backtest` | `tests/test_indicators.py::test_features_have_no_look_ahead` | Ejecución a la apertura siguiente: `tests/test_backtest.py::test_signal_on_last_bar_does_not_trade_and_end_of_data_closes` |
| R12.11 | Evitar survivorship bias | ⏳ | — | — | Depende del universo de datos reales (incluir deslistados) |
| R12.12 | Evitar data leakage | 🟡 | `packages/aqt/statistics/validation.py::purged_kfold_splits` | `tests/test_statistics.py::test_purged_kfold` | Embargo disponible; integrar en pipeline/ML |
| R12.13 | Evitar overfitting | 🟡 | `packages/aqt/statistics/validation.py::walk_forward` | `tests/test_research.py::test_random_walk_is_not_promoted` | OOS + WF + estabilidad; falta Deflated Sharpe / PBO |
| R12.14 | Evitar selection bias | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | La variante se selecciona sólo con IS y se congela |
| R12.15 | Evitar data snooping | 🟡 | `packages/aqt/research/study.py::run_study` | `tests/test_study.py::test_global_fdr_decides_candidates` | FDR sobre todo el estudio y nº de hipótesis guardado en `experiments`; falta control acumulado entre estudios sucesivos |
| R12.16 | Control de multiple hypothesis testing (FDR) | ✅ | `packages/aqt/statistics/multiple_testing.py::benjamini_hochberg` | `tests/test_statistics.py::test_benjamini_hochberg` | — |
| R12.17 | FDR global sobre miles de hipótesis (todo el universo) | ✅ | `packages/aqt/research/study.py::run_study` | `tests/test_study.py::test_global_fdr_decides_candidates` | BH sobre todas las variantes × estrategias × símbolos; sin superarlo no hay candidato |
| R12.18 | Mismo motor por eventos en vivo y en replay, sin look-ahead | ✅ | `packages/aqt/stream/engine.py::StreamingEngine`, `packages/aqt/stream/bars.py::BarAggregator` | `tests/test_stream.py::test_engine_on_synthetic_stream_is_deterministic` | Reloj de eventos; la vela se decide al llegar un evento posterior y la orden se llena tras la latencia: `tests/test_stream.py::test_features_are_causal_and_sane` |
| R12.19 | Validación forward (fuera de muestra por construcción) de estrategias en streaming | ✅ | `packages/aqt/stream/evidence.py::EvidenceTracker` | `tests/test_stream.py::test_evidence_requires_trades_and_controls_fdr` | Operaciones en sombra netas de costes, ventana móvil, BH-FDR entre estrategias |
| R12.20 | Simulación sobre historia real de alta frecuencia con el mismo motor | ✅ | `packages/aqt/stream/history.py::kline_events`, `services/trader/cli.py::simulate` | `tests/test_simulation.py::test_klines_become_conservative_quotes_and_signed_trades` | Velas de 1 s de Binance (precio + volumen comprador) → quotes con recorrido conservador y spread supuesto + trades firmados; evidencia empieza vacía (walk-forward real) |
| R12.21 | Indicadores a la escala temporal de cada estrategia | ✅ | `packages/aqt/stream/strategies.py::scaled_features` | `tests/test_simulation.py::test_strategies_use_features_scaled_to_their_horizon` | Corrige salidas prematuras: una idea a 20 min se juzga con tendencias de 20 min |
| R12.22 | Paridad research ↔ motor en vivo de cada regla | ✅ | `packages/aqt/stream/dsl_strategy.py::DslStreamStrategy` | `tests/test_dsl_stream.py::test_live_rule_matches_backtester_signals` | Mismos ticks → mismas velas, features y entradas que `run_backtest` |
| R12.23 | Comprobación golden: la regla validada debe ganar también en el motor real | ✅ | `packages/aqt/lab/cycle.py::golden_check` | `tests/test_lab.py::test_cycle_discovers_planted_edge_and_ignores_noise` | Replay del periodo fuera de muestra con latencia, bid/ask y comisiones |
| R12.24 | Research masivo en paralelo | ✅ | `packages/aqt/research/study.py::run_study` | `tests/test_lab.py::test_cycle_discovers_planted_edge_and_ignores_noise` | `workers` procesos; FDR global idéntico al secuencial. Real: 1.790 hipótesis (10 símbolos × 7 días) en ~7 min |
| R12.25 | Meta-labeling validado sin fugas | ✅ | `packages/aqt/lab/meta.py::train_meta_filter` | `tests/test_meta.py::test_meta_filter_refuses_noise_and_small_samples` | Purged K-fold, Bonferroni sobre umbrales; excluye niveles de precio y reloj |
| R12.26 | Research multi-timeframe con un único FDR global | ✅ | `packages/aqt/research/study.py::apply_global_fdr`, `packages/aqt/lab/cycle.py::run_research_cycle` | `tests/test_swing.py::test_multi_timeframe_cycle_finds_a_cross_sectional_leader` | Cripto 1min/1h/4h/1d, acciones 15min/1h/1d; todas las hipótesis de todos los timeframes cuentan en el mismo BH |
| R12.27 | Swing: reglas ≥ 1 h mantienen posiciones entre sesiones | ✅ | `packages/aqt/stream/engine.py::StreamingEngine`, `packages/aqt/stream/dsl_strategy.py::DslStreamStrategy` | `tests/test_swing.py::test_swing_positions_survive_the_close_intraday_ones_do_not` | Las intradía se cierran antes del cierre; las swing no, y sólo entran con mercado abierto |
| R12.28 | Paridad research ↔ vivo de las features entre valores | ✅ | `packages/aqt/stream/dsl_strategy.py::ResearchBarBook` | `tests/test_swing.py::test_live_cross_sectional_rule_matches_research` | El libro reconstruye el panel con todas las series del timeframe; mismas entradas que el research |
| R12.29 | Progreso del aprendizaje visible (embudo de hipótesis, reglas hacia champion, ML, IA, actividad) | ✅ | `packages/aqt/lab/progress.py::learning_progress`, `apps/dashboard/local/app.js` | `tests/test_progress.py::test_funnel_accumulates_every_cycle_and_rule_transitions`, `tests/test_progress.py::test_ml_progress_counts_examples_against_what_the_trainer_needs`, `tests/test_progress.py::test_rule_progress_and_learning_api` | Panel «Aprendizaje»: circuito cuyos nodos se iluminan y reciben chispas con cada novedad, y bolas que se llenan (reglas, machine learning, camino a real); detalle solo al pasar el ratón. `GET /api/learning` |
| R12.30 | Barras diarias en el lab con historia larga y familias sólo donde están documentadas | ✅ | `packages/aqt/lab/cycle.py::LabConfig`, `services/trader/cli.py::MARKETS` | `tests/test_swing.py::test_catalog_for_keeps_daily_and_equity_effects_where_documented` | `daily_days` = 5 años para 1d (warm-up de 252 barras + muestra); efectos diarios fuera de 1h/4h y de calendario de acciones fuera de cripto. La muestra por símbolo es pequeña: en 1d las reglas se prueban agrupadas (R12.32) |
| R12.31 | Paridad research ↔ vivo de las features de noticias | ✅ | `packages/aqt/stream/dsl_strategy.py::ResearchBarBook`, `packages/aqt/stream/dsl_strategy.py::DslStreamStrategy` | `tests/test_news.py::test_live_news_rule_matches_research`, `tests/test_news.py::test_news_rule_never_signals_without_a_news_source` | El libro en vivo pasa su `NewsBook` a `augment`; una regla que necesita features ausentes nunca da señal |
| R12.32 | Research agrupado (panel) de las reglas diarias sobre todo el universo | ✅ | `packages/aqt/research/panel.py::run_panel_research`, `packages/aqt/research/study.py::run_panel_study`, `packages/aqt/lab/cycle.py::LabConfig` | `tests/test_panel.py::test_pooling_finds_a_weak_effect_that_no_single_symbol_can_prove`, `tests/test_panel.py::test_one_frontier_for_all_symbols_and_dates_as_the_unit` | Mismo pipeline e informe que por símbolo; frontera IS/OOS y ventanas de walk-forward con fechas comunes; las operaciones se agregan por fecha de entrada (10 copias de un valor = la evidencia de uno); sus p-values entran en el FDR global. `panel_timeframes = ("1d",)` |
| R12.33 | Golden check agrupado en el motor real | ✅ | `packages/aqt/lab/cycle.py::golden_check_panel` | `tests/test_panel.py::test_lab_promotes_one_pooled_rule_that_trades_every_symbol` | Un único motor con todos los valores y la regla como una sola estrategia |
| R12.34 | Regla agrupada en vivo: una estrategia sobre todo el universo con evidencia conjunta | ✅ | `packages/aqt/stream/dsl_strategy.py::PanelDslStrategy`, `packages/aqt/lab/live.py::rule_strategies` | `tests/test_panel.py::test_pooled_rule_live_matches_research_on_every_symbol`, `tests/test_panel.py::test_lab_promotes_one_pooled_rule_that_trades_every_symbol` | Regla registrada con `symbol="*"`: ocupa un hueco, misma `strategy_id` en todos los valores (sombra, revisión y Risk Engine acumulan evidencia de todos); paridad con el research por valor |

## §13 Bayesian Evidence Engine

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R13.01 | Distinguir 95/100 de 9.500/10.000 | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | — |
| R13.02 | Distribuciones posteriores | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | Win rate; falta posterior del EV |
| R13.03 | Intervalos creíbles | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | — |
| R13.04 | Actualización bayesiana | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | `update_one` |
| R13.05 | Cada nueva operación real/paper actualiza la evidencia | ✅ | `packages/aqt/stream/evidence.py::EvidenceTracker` | `tests/test_stream.py::test_shutdown_closes_positions_and_evidence_persists` | Cada operación en sombra cerrada actualiza Edge Score (posterior Beta-Binomial) y p-valor; persiste en SQLite entre reinicios |
| R13.06 | Revisión forward de reglas vivas (promoción / retirada con lección) | ✅ | `packages/aqt/lab/review.py::review_rules` | `tests/test_lab.py::test_review_retires_losers_and_promotes_winners` | Retira si P(EV>0) < 0,2 tras ≥ 30 operaciones o si deja de dar señales |

## §14 Champion / Challenger

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R14.01 | Estados Champion / Challenger | ✅ | `packages/aqt/lab/registry.py::RuleStatus` | `tests/test_lab.py::test_review_retires_losers_and_promotes_winners` | Registro local: candidate → challenger → champion → retired; la tabla Supabase `strategies.status` queda para el despliegue |
| R14.02 | La IA no despliega cambios directamente | ✅ | `packages/aqt/lab/learning.py::learn_meta_filters`, `packages/aqt/lab/cycle.py::run_research_cycle` | `tests/test_meta.py::test_learning_registers_filtered_versions_of_baseline_strategies`, `tests/test_analyst.py::test_cycle_tests_pending_ai_hypotheses_in_the_global_fdr` | El ML sólo crea versiones challenger y las hipótesis de la IA sólo entran como candidatas del lab; ambas deben ganarse la promoción con evidencia forward |
| R14.03 | Pipeline Backtest → OOS → WF → costes | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Veredicto `CHALLENGER_CANDIDATE` |
| R14.04 | Paper trading antes de promoción | ✅ | `packages/aqt/lab/review.py::review_rules` | `tests/test_lab.py::test_review_retires_losers_and_promotes_winners` | Una regla del lab sólo pasa a champion (y a operar en paper) cuando su evidencia forward en sombra supera los umbrales del Risk Engine |
| R14.05 | Comparación con el Champion | ⏳ | — | — | — |
| R14.06 | Promoción auditada | ✅ | `packages/aqt/lab/registry.py::RuleRegistry` | `tests/test_lab.py::test_registry_upsert_and_transitions` | `rule_events` (motivo de cada transición) + `lessons`; tabla Supabase `strategy_promotions` para el despliegue |

## §15 Shadow Portfolios

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R15.01 | Cartera real (Champion) + carteras shadow paralelas | 🟡 | `packages/aqt/stream/engine.py::StreamingEngine` | `tests/test_stream.py::test_engine_without_evidence_trades_only_in_shadow` | Libro en sombra por estrategia (todas las señales, mismo modelo de ejecución) junto al libro paper; falta Champion explícito |
| R15.02 | Benchmark Buy & Hold | 🟡 | `packages/aqt/stream/engine.py::StreamingEngine` | `tests/test_simulation.py::test_engine_tracks_buy_and_hold_and_unfiltered_shadow` | Streaming: capital inicial repartido a partes iguales entre los símbolos, en la curva de equity y en el resumen de simulación; falta en research diario |
| R15.03 | Benchmark Cash | ⏳ | — | — | — |
| R15.04 | Comparación continua | ⏳ | — | — | `paper_runs` en el esquema |

## §16 Counterfactual Learning

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R16.01 | Guardar lo ocurrido y la alternativa contraria | 🟡 | `supabase/migrations/20261001000000_initial_schema.sql` | — | Columna `signals.counterfactual`; falta cálculo |
| R16.02 | Aprender de oportunidades rechazadas (NO BUY) | ✅ | `packages/aqt/lab/learning.py::learn_meta_filters`, `packages/aqt/stream/engine.py::StreamingEngine` | `tests/test_meta.py::test_learning_registers_filtered_versions_of_baseline_strategies` | Toda señal (aprobada o rechazada) se opera en sombra con su contexto; el meta-labeling aprende de ganadoras y perdedoras |

## §17 Risk Engine

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R17.01 | Sin LLM, determinista, cubierto por tests | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_property_approved_orders_never_exceed_limits` | CI exige ≥95 % de cobertura en risk/sizing |
| R17.02 | Maximum risk per trade | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_property_approved_orders_never_exceed_limits` | — |
| R17.03 | Maximum position exposure | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_adjust_size_when_position_cap_binds` | — |
| R17.04 | Maximum portfolio exposure | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_portfolio_exposure_cap` | — |
| R17.05 | Maximum daily loss | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.06 | Maximum drawdown | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.07 | Maximum consecutive losses | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.08 | Minimum liquidity | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | ADV > 0 y participación máx. en volumen |
| R17.09 | Maximum spread | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.10 | Minimum expected edge | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | Edge score, confianza y EV neto con costes en vivo |
| R17.11 | Maximum slippage | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.12 | Stale market data protection | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | También rechaza timestamps futuros |
| R17.13 | Duplicate order protection | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | Más idempotencia en broker: `tests/test_brokers.py::test_idempotency_and_rejections` |
| R17.14 | Trading-hours validation | 🟡 | `packages/aqt/stream/session.py::UsEquitySession` | `tests/test_stocks.py::test_engine_is_intraday_only_for_stocks` | Cripto 24/7; acciones 09:30–16:00 NY, sin entradas en los últimos 15 min y cierre 5 min antes. Falta cablear festivos del calendario Alpaca (`packages/aqt/stream/alpaca.py::fetch_trading_days`) |
| R17.15 | API health validation | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.16 | Portfolio reconciliation | ✅ | `packages/aqt/brokers/alpaca_paper.py::AlpacaPaperBroker`, `packages/aqt/stream/engine.py::StreamingEngine` | `tests/test_alpaca_paper.py::test_persistent_mismatch_or_blocked_account_makes_venue_unhealthy` | Con Alpaca paper: posiciones del bot vs las que reporta el broker cada 15 s; un descuadre persistente marca la API no sana y el Risk Engine bloquea. Falta en Trading 212 |
| R17.17 | Kill switch | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_sell_exits_allowed_shorts_forbidden` | También flag `GLOBAL_KILL_SWITCH`: `tests/test_config.py::test_invalid_mode_and_kill_switch` |
| R17.18 | Cualquier fallo → TRADE REJECTED | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.19 | Salida APPROVE / REJECT / ADJUST_SIZE | ✅ | `packages/aqt/risk/engine.py::RiskAction` | `tests/test_risk.py::test_adjust_size_when_position_cap_binds` | — |

## §18 Cost awareness

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R18.01 | Gross edge − fees − FX − spread − slippage = net edge | ✅ | `packages/aqt/backtest/costs.py::CostModel` | `tests/test_backtest.py::test_costs_reduce_returns_and_equity_matches_trades` | — |
| R18.02 | Descartar estrategias que sólo funcionan antes de costes | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Check `edge_after_costs` |
| R18.03 | Filtro económico por operación en vivo | ✅ | `packages/aqt/risk/engine.py::RiskEngine`, `packages/aqt/stream/strategies.py::StreamStrategy` | `tests/test_stream.py::test_cost_gate_blocks_moves_that_cannot_pay_fees` | `min_expected_net_edge` + en streaming el objetivo debe ser ≥ 2× el coste ida y vuelta en vivo (fees + spread + slippage) |
| R18.04 | Comisiones fijas relevantes con cuentas pequeñas | ✅ | `packages/aqt/backtest/costs.py::CostModel` | `tests/test_backtest.py::test_cost_model_validation` | Coste calculado sobre el nocional real |
| R18.05 | Tarifas reales de Trading 212 (FX 0,15 %, etc.) verificadas | 🟡 | `packages/aqt/backtest/costs.py::CostModel` | `tests/test_yahoo.py::test_trading212_costs` | `CostModel.trading212`: sin comisión, FX 0,15 % por lado si la divisa ≠ EUR, spread/slippage conservadores. Verificar tarifas vigentes antes de Live |

## §19 AI Analyst

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R19.01 | El LLM nunca envía órdenes | ✅ | `packages/aqt/analyst/hypotheses.py::run_analyst` | `tests/test_analyst.py::test_analyst_package_cannot_import_brokers_risk_or_the_engine` | Sin imports de brokers/riesgo/motor/servicios, ni directos ni transitivos; nunca ve claves de broker (sólo `OPENAI_API_KEY`) |
| R19.02 | Análisis de operaciones, errores, régimen, anomalías, degradación | 🟡 | `packages/aqt/analyst/hypotheses.py::build_context` | `tests/test_analyst.py::test_run_analyst_stores_valid_rejects_invalid_and_dedupes` | Lee lecciones, checks que fallan, mejores pares, evidencia forward y sus hipótesis previas; falta análisis de operaciones y anomalías |
| R19.03 | Generación de hipótesis y Challengers | ✅ | `packages/aqt/analyst/hypotheses.py::run_analyst` | `tests/test_analyst.py::test_run_analyst_stores_valid_rejects_invalid_and_dedupes` | Hipótesis en el DSL (familia `ai`) con grid ≤ 8 variantes; tabla `hypotheses` en SQLite |
| R19.04 | Literatura, noticias, macro, lecciones | 🟡 | `packages/aqt/analyst/hypotheses.py::build_context`, `packages/aqt/analyst/briefing.py::build_briefing_context` | `tests/test_briefing.py::test_context_tells_the_date_the_market_status_and_only_real_headlines` | Lecciones del lab y noticias reales del día (R19.09) sí; literatura y macro pendientes |
| R19.05 | Salida estructurada | ✅ | `packages/aqt/analyst/hypotheses.py::validate_proposal` | `tests/test_analyst.py::test_invalid_proposals_are_rejected_with_a_reason` | JSON mode + validación estricta (Claim / Evidence / Suggested experiment + regla DSL); lo inválido se guarda con motivo. Tablas Supabase `ai_hypotheses` sin sincronizar aún |
| R19.06 | El Research Engine confirma o rechaza las hipótesis | ✅ | `packages/aqt/lab/cycle.py::run_research_cycle` | `tests/test_analyst.py::test_cycle_tests_pending_ai_hypotheses_in_the_global_fdr` | Las hipótesis pendientes se examinan en el mismo FDR global; veredicto (`promoted`/`rejected`, checks que fallan) vuelve al analista |
| R19.07 | Límites de coste del analista: presupuesto diario, deduplicación | ✅ | `packages/aqt/analyst/hypotheses.py::run_analyst`, `packages/aqt/analyst/briefing.py::run_briefing` | `tests/test_analyst.py::test_run_analyst_respects_the_daily_budget_and_api_errors`, `tests/test_briefing.py::test_run_briefing_stores_it_queues_hypotheses_and_respects_the_budget` | Máx. 6 llamadas/día por defecto, compartidas con el resumen de noticias (1 al día); duplicados por contenido de la regla (no por nombre); errores de la API no rompen el ciclo |
| R19.08 | Panel «Analista IA» en el dashboard con el veredicto del lab | ✅ | `services/trader/app.py::create_app`, `services/trader/lab_scheduler.py::LabScheduler` | `tests/test_lab_service.py::test_lab_endpoints` | `GET /api/hypotheses` y `hypotheses` en `/api/research` |
| R19.09 | «Noticias del día»: el analista resume los titulares reales del día sabiendo la fecha | ✅ | `packages/aqt/analyst/briefing.py::run_briefing`, `packages/aqt/analyst/briefing.py::validate_briefing`, `services/trader/cli.py::news` | `tests/test_briefing.py::test_run_briefing_stores_it_queues_hypotheses_and_respects_the_budget`, `tests/test_briefing.py::test_validation_discards_invented_ids_symbols_and_watchlist`, `tests/test_briefing.py::test_briefing_survives_api_errors_and_bad_answers`, `tests/test_briefing.py::test_news_cli_needs_keys_shows_the_date_and_runs_the_briefing` | Petición del usuario (2026-10-02). Recibe fecha y hora de Nueva York y UTC, si hoy abre el mercado y hasta 120 titulares de Alpaca News con su id; cada evento debe citar ids reales y sus símbolos deben estar en esos titulares (lo demás se descarta y se muestra). Sus hipótesis van a la cola del analista; nunca opera y su texto nunca es feature de backtest |
| R19.10 | Panel «Noticias del día» y `GET /api/news` | ✅ | `services/trader/app.py::create_app`, `apps/dashboard/local/app.js` | `tests/test_briefing.py::test_api_news_serves_the_latest_briefing` | Resumen, eventos por importancia con enlace a los titulares citados, watchlist, lo descartado y el estado del sondeo de titulares |
| R19.11 | Resumen de noticias automático cada día de mercado antes de la apertura | ✅ | `services/trader/lab_scheduler.py::LabScheduler`, `services/trader/lab_scheduler.py::news_runner` | `tests/test_briefing.py::test_scheduler_runs_the_briefing_once_per_new_york_weekday_after_08_45` | Lunes a viernes desde las 08:45 de Nueva York, un intento al día en un proceso aparte; sólo si hay claves de Alpaca y `OPENAI_API_KEY` |

## §20 Memoria (Supabase)

Todas las tablas están creadas en el proyecto "Autonomous trading" con RLS, marcador `aqt`,
lectura para `authenticated`, sin acceso `anon` y escritura sólo vía `service_role`.

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R20.01 | Tablas de §20 creadas (strategies … configuration) | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | 22 tablas aplicadas y verificadas vía MCP |
| R20.02 | RLS en todas las tablas | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | — |
| R20.03 | Privilegios mínimos (anon sin acceso, dashboard sólo lectura + slider/kill switch) | ✅ | `supabase/migrations/20261001010000_harden_privileges.sql` | — | Advisor de seguridad de Supabase sin avisos |
| R20.04 | Auditoría de cambios de configuración | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | Trigger → `config_audit_log` |
| R20.05 | Persistencia desde Python (cliente Supabase) | 🟡 | `packages/aqt/persistence/store.py::SupabaseStore` | `tests/test_persistence.py::test_failure_marks_experiment_failed` | Escribe `experiments`, `strategies`, `strategy_versions`, `backtests`, `walk_forward_runs` vía PostgREST; pendiente primera ejecución real |
| R20.06 | La memoria del LLM no es almacenamiento principal | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | — |
| R20.07 | Memoria de aprendizaje local (reglas, transiciones, lecciones, ciclos) | ✅ | `packages/aqt/lab/registry.py::RuleRegistry` | `tests/test_lab.py::test_registry_upsert_and_transitions` | SQLite por mercado (`aqt.sqlite`, `stocks.sqlite`); modelos ML versionados con hash |

## §21–22 Arquitectura y uso de Lovable

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R21.01 | Research / Trading / Risk en Python | ✅ | `packages/aqt` | — | Trading: trader en streaming (paper) en `packages/aqt/stream` + `services/trader` |
| R21.02 | Historical data en Parquet + DuckDB | ✅ | `packages/aqt/data/store.py::ParquetStore` | `tests/test_data.py::test_parquet_roundtrip` | — |
| R21.03 | Supabase PostgreSQL | ✅ | `supabase/migrations` | — | — |
| R21.04 | Worker en Railway | ⏳ | `docs/despliegue-railway.md` | — | Guía escrita, sin implementar (aparcado por el usuario, 2026-10-02): Dockerfile, volumen para `data/`, variables, reinicio; requiere antes acceso autenticado al dashboard |
| R21.05 | Frontend Lovable / Next.js en Vercel | ⏳ | `apps/dashboard/README.md` | — | — |
| R21.06 | BrokerAdapter abstracto | ✅ | `packages/aqt/brokers/base.py::BrokerAdapter` | `tests/test_brokers.py::test_simulated_buy_sell_cycle` | — |
| R21.07 | Trading212Adapter | ⏳ | `packages/aqt/brokers/trading212.py::Trading212Broker` | `tests/test_brokers.py::test_trading212_guardrails` | Stub con guardarraíles |
| R21.08 | IBKRAdapter (futuro) | ⏳ | — | — | — |
| R21.09 | MarketDataAdapter intercambiable | ✅ | `packages/aqt/data/adapters.py::MarketDataAdapter` | `tests/test_data.py::test_csv_adapter` | — |
| R21.10 | Datos de mercado en tiempo real (WebSocket) con reconexión | ✅ | `packages/aqt/stream/binance.py::BinanceFeed` | `tests/test_stream.py::test_parse_binance_messages` | Binance spot público (bookTicker + aggTrade), sin claves; TLS con el almacén del sistema |
| R21.11 | Grabación de ticks para replay / backtest | ✅ | `packages/aqt/stream/store.py::SQLiteStore`, `services/trader/cli.py::replay` | `tests/test_trader_service.py::test_cli_replay_and_ticks` | — |
| R21.12 | Exchange paper realista contra el libro real | ✅ | `packages/aqt/brokers/paper.py::PaperExchange` | `tests/test_stream.py::test_paper_impact_beyond_top_of_book` | Latencia, bid/ask, impacto más allá del top of book, comisión 0,10 %, mínimo nocional, sin cortos |
| R21.13 | Persistencia local en SQLite (decisiones, órdenes, operaciones, equity, controles) | ✅ | `packages/aqt/stream/store.py::SQLiteStore` | `tests/test_stream.py::test_store_ticks_roundtrip_and_settings` | Modo WAL; Supabase sigue siendo la memoria de research |
| R21.14 | Dashboard local (localhost) en tiempo real | ✅ | `apps/dashboard/local/app.js`, `services/trader/app.py::create_app` | `tests/test_trader_service.py::test_foreign_origins_are_refused` | FastAPI + WebSocket; sólo 127.0.0.1 y rechaza orígenes ajenos; controles: kill switch, pausa, cerrar todo, agresividad |
| R21.15 | Broker Binance real (órdenes) | ⏳ | — | — | Sólo datos públicos y paper; LIVE rechazado por el CLI hasta implementar adaptador + go-live gate |
| R21.16 | Simulación visual en el dashboard (fecha simulada, progreso, velocidad) | ✅ | `packages/aqt/stream/history.py::HistoricalFeed`, `services/trader/runtime.py::TraderRuntime` | `tests/test_simulation.py::test_simulation_runtime_reports_progress_and_speed` | Los controles de una simulación no se persisten ni afectan a la cuenta en vivo |
| R21.17 | Datos en tiempo real de acciones (Alpaca IEX) | ✅ | `packages/aqt/stream/alpaca.py::AlpacaFeed` | `tests/test_stocks.py::test_alpaca_parser_signs_trades` | Quotes + trades firmados (regla de la cotización + tick rule); requiere claves paper gratuitas en `.env` |
| R21.18 | Universo automático (top N por volumen) | ✅ | `packages/aqt/stream/binance.py::rank_symbols` | `tests/test_stream.py::test_rank_symbols_picks_liquid_non_stable_pairs` | Por defecto los 10 pares USDC más líquidos (excluye stablecoins) |
| R21.19 | Historia intradía de acciones (Yahoo sin clave, Alpaca con clave) | ✅ | `packages/aqt/stream/stocks.py::parse_yahoo_chart`, `packages/aqt/stream/alpaca.py::parse_alpaca_bars` | `tests/test_stocks.py::test_parse_yahoo_chart` | Yahoo ~7 días de velas de 1 min; Alpaca años (sesión regular) |
| R21.20 | Investigación y simulación de acciones | ✅ | `packages/aqt/lab/cycle.py::BarData`, `services/trader/cli.py::simulate` | `tests/test_stocks.py::test_lab_cycle_runs_on_stock_bars` | `--market stocks` en `research`, `simulate` y `run` |
| R21.21 | Broker Alpaca **paper**: órdenes reales a la cuenta simulada, subcuenta de capital, sin margen | ✅ | `packages/aqt/brokers/alpaca_paper.py::AlpacaPaperBroker` | `tests/test_alpaca_paper.py::test_orders_are_routed_filled_and_reconciled` | `run --market stocks --broker alpaca --cash N`; sólo `paper-api.alpaca.markets` (cualquier otro host se rechaza); toda orden sigue pasando por el Risk Engine |
| R21.22 | Historia larga a varias escalas (klines Binance, barras Alpaca remuestreadas) | ✅ | `packages/aqt/stream/history.py::load_binance_klines`, `packages/aqt/stream/alpaca.py::load_alpaca_bars` | `tests/test_swing.py::test_resample_and_kline_rows` | Caché mensual en Parquet; barras alineadas a fronteras UTC; BVC al timeframe |
| R21.23 | Adaptador Alpaca News (titulares históricos con hora de publicación) con caché | ✅ | `packages/aqt/news/alpaca.py::fetch_news`, `packages/aqt/news/alpaca.py::load_alpaca_news` | `tests/test_news.py::test_fetch_news_paginates_oldest_first` | Mismas claves paper que las barras; caché por símbolo y mes en `data/stream/alpaca_news`; 3 años de historia por defecto (`news_days`); la primera descarga tarda (límite de 200 peticiones/min) |
| R21.24 | Noticias en vivo para las reglas del trader de acciones | ✅ | `services/trader/news_poller.py::NewsPoller`, `services/trader/runtime.py::TraderRuntime` | `tests/test_news.py::test_news_poller_backfills_then_overlaps_and_survives_errors` | Backfill de 22 días y sondeo cada minuto con solape; un fallo no detiene el trading; estado en `/api/state` (`news`) |
| R22.01 | El núcleo no se implementa en Lovable | ✅ | `apps/dashboard/README.md` | — | — |
| R22.02 | El frontend nunca tiene claves del broker | ✅ | `.env.example` | — | Sólo backend; dashboard usa anon key + Auth |

## §23–25 Entorno y runtime

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R23.01 | Monorepo con la estructura recomendada | ✅ | `packages/aqt`, `services`, `apps/dashboard`, `supabase/migrations`, `docs`, `infra` | — | Paquetes como subpaquetes de `aqt` |
| R23.02 | Ramas main / develop | ⏳ | — | — | Hoy se trabaja en rama de feature; crear `develop` |
| R23.03 | CI con lint, tipos, tests y escaneo de secretos | ✅ | `.github/workflows/ci.yml` | — | ruff, mypy, pytest, gitleaks |
| R25.01 | El bot es un servicio Python (no vive en el agente) | ✅ | `services/trader/cli.py::run` | `tests/test_trader_service.py::test_runtime_consumes_feed_records_ticks_and_stops_cleanly` | Proceso local (`python -m services.trader run`); despliegue en Railway pendiente (R21.04) |
| R25.02 | Cron: scanner, daily review, research, AI review, reconciliación | 🟡 | `services/trader/lab_scheduler.py::LabScheduler` | `tests/test_lab_service.py::test_scheduler_runs_research_reviews_and_hot_loads_rules` | Research cada 6 h (proceso aparte) + revisión y meta-learning cada hora dentro del trader local; AI review y despliegue en Railway pendientes |
| R25.03 | Sin LLM por tick | ✅ | `services/ai_analyst/README.md` | — | Ningún camino de ejecución llama a un LLM |

## §26–29 Broker, OpenAI y cuentas

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R26.01 | Trading 212: entornos Demo y Live separados | ✅ | `packages/aqt/brokers/trading212.py::Trading212Broker` | `tests/test_brokers.py::test_trading212_guardrails` | URLs demo/live según modo |
| R26.02 | Credenciales API key + secret desde secretos, nunca en código | ✅ | `.env.example` | `tests/test_brokers.py::test_trading212_guardrails` | `repr` no filtra secretos |
| R26.03 | Restricción de claves por IP | ⏳ | — | — | Manual en Trading 212 al crear las claves |
| R26.04 | Órdenes fraccionarias | ✅ | `packages/aqt/risk/models.py::MarketState` | `tests/test_risk.py::test_small_account_100_eur` | `quantity_step` |
| R26.05 | Revalidar limitaciones de la API beta antes de Live | ⏳ | — | — | — |
| R26.06 | Mercado para el trader en streaming: cripto spot en Binance (pares de una única divisa de cotización) | ✅ | `packages/aqt/stream/binance.py::quote_currency` | `tests/test_stream.py::test_symbol_info_and_quote_currency` | Decisión del usuario (2026-10-01): Trading 212 no ofrece streaming ni la frecuencia de órdenes necesaria |
| R28.01 | Proyecto OpenAI con key propia, presupuesto y logging | ⏳ | `.env.example` | — | Manual (usuario) |
| R28.02 | Modelo barato frecuente / potente para research | ⏳ | `.env.example` | — | `OPENAI_MODEL_CHEAP` / `OPENAI_MODEL_STRONG` |
| R29.01 | Cuenta GitHub | ✅ | — | — | — |
| R29.02 | Cuenta Supabase | ✅ | — | — | Proyecto "Autonomous trading" |
| R29.03 | Cuenta Railway | ⏳ | — | — | — |
| R29.04 | Cuenta Trading 212 Invest (Demo) | ⏳ | — | — | — |
| R29.05 | Cuenta OpenAI Platform | ⏳ | — | — | — |
| R29.06 | Cuenta Vercel | ⏳ | — | — | — |
| R29.07 | Cuenta Lovable | ⏳ | — | — | — |
| R29.08 | Cuenta Binance (sólo para LIVE futuro) | ⏳ | — | — | No necesaria para datos ni paper |
| R29.09 | Cuenta Alpaca (claves paper para datos en tiempo real e historia) | ⏳ | `.env.example` | — | Manual (usuario): sin claves, `run --market stocks` explica cómo obtenerlas |

## §30 Hoja de ruta

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R30.01 | Paso 1 — Repositorio, CI, tests, secretos, `.env.example` | 🟡 | `.github/workflows/ci.yml` | — | Falta rama `develop` (R23.02) |
| R30.02 | Paso 2 — Supabase | 🟡 | `supabase/migrations` | — | Esquema, RLS, auditoría ✅; Vault, Storage y Auth sin configurar |
| R30.03 | Paso 3 — Research Engine + CLI con informe reproducible | ✅ | `services/research/cli.py` | `tests/test_research.py::test_cli` | — |
| R30.04 | Paso 4 — Strategy DSL | ✅ | `packages/aqt/strategies/dsl.py::StrategySpec` | `tests/test_dsl.py::test_render_and_grid` | — |
| R30.05 | Paso 5 — Statistical Validation Engine | ✅ | `packages/aqt/statistics` | `tests/test_statistics.py::test_split_and_walk_forward` | Ver §12 para parciales |
| R30.06 | Paso 6 — Risk Engine aislado | ✅ | `packages/aqt/risk` | `tests/test_risk.py::test_each_check_rejects` | — |
| R30.07 | Paso 7 — Cuenta Demo Trading 212 | ⏳ | — | — | Manual (usuario) |
| R30.08 | Paso 8 — BrokerAdapter + Trading212Broker | 🟡 | `packages/aqt/brokers/base.py::BrokerAdapter` | `tests/test_brokers.py::test_simulated_buy_sell_cycle` | Interfaz ✅; implementación T212 ⏳ |
| R30.09 | Paso 9 — Paper Trader | 🟡 | `packages/aqt/brokers/alpaca_paper.py::AlpacaPaperBroker`, `services/trader/cli.py::run` | `tests/test_alpaca_paper.py::test_engine_trades_through_alpaca_paper` | Paper con fills locales (Binance/acciones) y paper contra un broker real (Alpaca paper: órdenes enviadas y fills del broker) ✅; Trading 212 Demo ⏳ |
| R30.10 | Paso 10 — Shadow Engine | 🟡 | `packages/aqt/stream/engine.py::StreamingEngine` | `tests/test_stream.py::test_engine_without_evidence_trades_only_in_shadow` | Libro en sombra por estrategia; faltan Buy & Hold / Cash (R15.02–R15.03) |
| R30.11 | Paso 11 — AI Analyst | ✅ | `packages/aqt/analyst/client.py::OpenAIClient`, `services/trader/cli.py::analyst` | `tests/test_analyst.py::test_analyst_cli_dry_run_off_and_mocked_call` | Local: `python -m services.trader analyst` o antes de cada ciclo de research (cada 6 h con el lab); presupuesto diario de llamadas |
| R30.12 | Paso 12 — Autonomous Research Loop | 🟡 | `packages/aqt/lab/cycle.py::run_research_cycle`, `services/trader/lab_scheduler.py::LabScheduler` | `tests/test_lab.py::test_cycle_discovers_planted_edge_and_ignores_noise` | Bucle local completo (research → golden → challenger → review → meta-learning); Railway pendiente |
| R30.13 | Paso 13 — Dashboard | 🟡 | `apps/dashboard/local/index.html`, `services/trader/app.py::create_app` | `tests/test_trader_service.py::test_api_state_control_and_persistence` | Dashboard local en localhost ✅; versión Lovable/Vercel ⏳ |
| R30.14 | Paso 14 — Deploy | ⏳ | `docs/despliegue-railway.md` | — | Aparcado; guía para retomarlo en Railway (R21.04) |
| R30.15 | Paso 15 — Seguridad: entornos y doble flag LIVE | ✅ | `packages/aqt/common/config.py::load_settings` | `tests/test_config.py::test_live_requires_both_flags` | — |
| R30.16 | Paso 15 — Claves distintas por entorno | 🟡 | `.env.example` | — | Variables separadas demo/live; falta gestor de secretos |
| R30.17 | Paso 15 — Global kill switch en dashboard | ✅ | `services/trader/app.py::create_app`, `services/trader/runtime.py::TraderRuntime` | `tests/test_trader_service.py::test_api_state_control_and_persistence` | Local: botón en el dashboard, leído por el trader y persistido; columna Supabase auditada para la versión desplegada |
| R30.18 | Paso 16 — Go-live gate | 🟡 | `packages/aqt/stream/golive.py::evaluate_gate`, `services/trader/golive_monitor.py::GoLiveMonitor` | `tests/test_golive.py::test_gate_passes_with_a_month_of_consistent_beating_paper` | Puerta automática con aviso; falta el adaptador de broker real (nada pasa a LIVE solo) |
| R30.19 | Menú de arranque local con cada modo explicado (solo PAPER) | ✅ | `services/launcher/catalog.py::MODES`, `services/launcher/app.py::LauncherApp` | `tests/test_launcher.py::test_every_option_exists_in_the_real_cli_and_nothing_is_live`, `tests/test_launcher.py::test_menu_shows_modes_builds_the_command_and_launches` | `AQT.cmd` (doble clic) / `aqt.sh`: modos (incluido «Noticias del día»), para qué sirven, campos con ayuda y validación, comando visible; avisa si faltan claves |

## §31 Go-live gate y configuración LIVE inicial

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R31.01 | Evidencia out-of-sample | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_random_walk_is_not_promoted` | Herramienta lista; falta evidencia con datos reales |
| R31.02 | EV positivo después de costes | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Ídem |
| R31.03 | Drawdown dentro del límite | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Check `drawdown_within_limit` (Monte Carlo) |
| R31.04 | Estabilidad por régimen | 🟡 | `packages/aqt/statistics/regimes.py::metrics_by_regime` | — | Se reporta; aún no es criterio del veredicto |
| R31.05 | Paper trading consistente | ✅ | `packages/aqt/stream/golive.py::evaluate_gate` | `tests/test_golive.py::test_gate_names_what_is_missing` | ≥ 28 días, ≥ 50 operaciones, neto > 0, t-test p < 0,05, ≥ 3 de 4 semanas positivas, mejor que Buy & Hold, caída ≤ límite del perfil |
| R31.06 | Ausencia de errores de reconciliación | ✅ | `services/trader/golive_monitor.py::GoLiveMonitor` | `tests/test_golive.py::test_monitor_records_incidents_and_notifies_once_per_flip` | Descuadres que persisten dos muestras (15 s) quedan en `ops_events`; la puerta exige 0 y un broker externo (Alpaca paper) |
| R31.07 | Kill switch probado end-to-end | 🟡 | `packages/aqt/stream/engine.py::StreamingEngine`, `services/trader/runtime.py::TraderRuntime` | `tests/test_stream.py::test_kill_switch_pause_and_throttle_block_entries`, `tests/test_golive.py::test_runtime_api_kill_switch_events_and_loop` | Activar/desactivar queda auditado y la puerta exige haberlo probado en la cuenta paper; falta con broker real |
| R31.08 | Recuperación del broker probada | 🟡 | `services/trader/golive_monitor.py::GoLiveMonitor` | `tests/test_golive.py::test_monitor_records_incidents_and_notifies_once_per_flip` | Caídas y recuperaciones del broker se registran (`broker_down`/`broker_recovered`); falta un simulacro forzado |
| R31.09 | Gate automatizado (checklist ejecutable) | ✅ | `packages/aqt/stream/golive.py::evaluate_gate`, `apps/dashboard/local/index.html` | `tests/test_golive.py::test_gate_passes_with_a_month_of_consistent_beating_paper`, `tests/test_golive.py::test_runtime_api_kill_switch_events_and_loop` | 10 criterios evaluados cada hora con su grado de avance; panel «Puerta a real» con barra de progreso, bola «Camino a real» y `GET /api/golive` |
| R31.10 | Config LIVE inicial: 100 €, límites estrictos, pocas posiciones | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_small_account_100_eur` | `configuration.aggressiveness` por defecto 20 |
| R31.11 | Aviso al operador cuando la puerta cambia de estado | ✅ | `services/trader/notify.py::make_notifier`, `services/trader/golive_monitor.py::GoLiveMonitor` | `tests/test_golive.py::test_notifier_ntfy_json_and_failures`, `tests/test_golive.py::test_monitor_records_incidents_and_notifies_once_per_flip` | Un aviso por cambio (listo / ya no listo): banner en el dashboard, log y webhook opcional `NOTIFY_WEBHOOK_URL` (ntfy al móvil, Slack, Discord) |

## §32–34 Escalabilidad, métrica y objetivo final

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R32.01 | Nada depende de que el capital sea 100 € | ✅ | `packages/aqt/sizing/engine.py::PositionSizingEngine` | `tests/test_sizing.py::test_scales_with_capital` | — |
| R33.01 | Métrica principal: risk-adjusted OOS expectancy | ✅ | `packages/aqt/research/report.py::render_markdown` | `tests/test_research.py::test_report_files` | EV OOS, IC, Sharpe/Sortino OOS en el informe |
| R34.01 | Ciclo autónomo completo market data → … → new research | 🟡 | `services/trader/lab_scheduler.py::LabScheduler` | `tests/test_lab_service.py::test_simulate_learn_headless` | Cerrado en local para el trader en streaming (también reproducible en simulación con `--learn`); faltan AI Analyst y despliegue |

---

## Cómo mantener este documento

1. **Cualquier commit** que implemente, cambie o elimine algo relacionado con un requisito
   actualiza su fila (estado, implementación, tests, notas) **en el mismo commit**, y menciona el
   ID en el mensaje (p. ej. `R17.14: market calendar`).
2. Si aparece un requisito nuevo o se descompone uno existente, se añade una fila con ID nuevo;
   los IDs nunca se reutilizan ni se renumeran.
3. Formato de referencias: rutas entre backticks; `ruta.py::Símbolo` para código y
   `tests/x.py::test_nombre` para tests. `tests/test_traceability.py` comprueba que existen.
4. Tras editar filas, regenera el resumen con `uv run python tests/test_traceability.py`
   (reescribe el bloque entre los marcadores `summary`).
5. Actualiza la fecha de *Última actualización* y, si cambia un paso de la hoja de ruta,
   también `docs/roadmap.md`.
