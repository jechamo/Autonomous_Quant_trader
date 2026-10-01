# Matriz de trazabilidad del PRD

Seguimiento requisito por requisito de [`docs/PRD.md`](PRD.md). Cada fila es un requisito atómico
con ID estable (`R<sección>.<nº>`), su estado, dónde está implementado, qué test lo cubre y qué
falta. `tests/test_traceability.py` verifica en CI que todas las rutas, símbolos y tests citados
existen y que el resumen cuadra con las filas.

**Leyenda:** ✅ hecho · 🟡 parcial · ⏳ pendiente · 🚫 excluido por diseño (y forzado en código)

**Última actualización:** 2026-10-01 · iteración 1 + hardening Supabase

<!-- summary:start -->
| Estado | Requisitos |
|---|---|
| ✅ | 123 |
| 🟡 | 26 |
| ⏳ | 71 |
| 🚫 | 7 |
| **Total** | **227** |

| Sección | ✅ | 🟡 | ⏳ | 🚫 | Total |
|---|---|---|---|---|---|
| §1 | 1 | 1 | 2 | 0 | 4 |
| §2 | 2 | 0 | 1 | 0 | 3 |
| §3 | 4 | 1 | 0 | 0 | 5 |
| §4 | 3 | 0 | 0 | 0 | 3 |
| §5 | 3 | 0 | 0 | 0 | 3 |
| §6 | 3 | 1 | 0 | 0 | 4 |
| §7 | 11 | 1 | 0 | 0 | 12 |
| §8 | 2 | 1 | 0 | 0 | 3 |
| §9 | 4 | 2 | 6 | 0 | 12 |
| §10 | 5 | 0 | 10 | 7 | 22 |
| §11 | 18 | 0 | 6 | 0 | 24 |
| §12 | 11 | 4 | 2 | 0 | 17 |
| §13 | 4 | 0 | 1 | 0 | 5 |
| §14 | 1 | 3 | 2 | 0 | 6 |
| §15 | 0 | 0 | 4 | 0 | 4 |
| §16 | 0 | 1 | 1 | 0 | 2 |
| §17 | 17 | 2 | 0 | 0 | 19 |
| §18 | 4 | 0 | 1 | 0 | 5 |
| §19 | 0 | 2 | 4 | 0 | 6 |
| §20 | 5 | 0 | 1 | 0 | 6 |
| §21 | 4 | 1 | 4 | 0 | 9 |
| §22 | 2 | 0 | 0 | 0 | 2 |
| §23 | 2 | 0 | 1 | 0 | 3 |
| §25 | 1 | 0 | 2 | 0 | 3 |
| §26 | 3 | 0 | 2 | 0 | 5 |
| §28 | 0 | 0 | 2 | 0 | 2 |
| §29 | 2 | 0 | 5 | 0 | 7 |
| §30 | 5 | 5 | 8 | 0 | 18 |
| §31 | 4 | 1 | 5 | 0 | 10 |
| §32 | 1 | 0 | 0 | 0 | 1 |
| §33 | 1 | 0 | 0 | 0 | 1 |
| §34 | 0 | 0 | 1 | 0 | 1 |
<!-- summary:end -->

---

## §1 Visión

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R1.01 | Núcleo de decisión cuantitativo, estadístico y determinista (no LLM) | ✅ | `packages/aqt/research/pipeline.py::run_research`, `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_research.py::test_pipeline_is_reproducible` | — |
| R1.02 | Toda ejecución atraviesa un Risk Engine independiente | 🟡 | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | El Risk Engine existe; falta el Trader que lo encadene obligatoriamente antes del broker (R30.09) |
| R1.03 | Gestionar 100 € reales sin aportaciones | ⏳ | — | `tests/test_risk.py::test_small_account_100_eur` | Sizing y riesgo probados con 100 €; operar real depende del go-live gate (§30 paso 16) |
| R1.04 | IA como investigador/analista/generador de hipótesis/Challengers | ⏳ | `services/ai_analyst/README.md` | — | Iteración 3 |

## §2–3 Evidencia cuantificable y conceptos

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R2.01 | Cada señal con evidencia: muestra, P(win) e IC, ganancia/pérdida media, EV, PF, MDD | ✅ | `packages/aqt/statistics/metrics.py::compute_metrics`, `packages/aqt/statistics/confidence.py::wilson_interval` | `tests/test_statistics.py::test_metrics_basic` | Incluido en el informe de research |
| R2.02 | Evidencia ligada al régimen de mercado | ✅ | `packages/aqt/statistics/regimes.py::metrics_by_regime` | `tests/test_research.py::test_pipeline_is_reproducible` | — |
| R2.03 | Signal Engine en vivo que adjunte la evidencia a cada señal | ⏳ | `packages/aqt/risk/models.py::StrategyEvidence` | — | El modelo de datos existe; falta generar señales en vivo (iteración 2) |
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
| R7.12 | Slider editable desde el dashboard | 🟡 | `supabase/migrations/20261001010000_harden_privileges.sql` | — | Columna `configuration.aggressiveness` editable y auditada; falta UI y que el trader la lea |

## §8 NO TRADE es una decisión

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R8.01 | El sistema no está obligado a invertir | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_random_walk_is_not_promoted` | — |
| R8.02 | Mantener caja si no hay oportunidades (reserva) | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_cash_reserve_cap` | Ver R7.10 |
| R8.03 | NO TRADE registrado como decisión | 🟡 | `supabase/migrations/20261001000000_initial_schema.sql` | — | `signals.decision` admite `NO_TRADE`; falta que el trader lo escriba |

## §9 Research Engine — stack

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R9.01 | Python | ✅ | `pyproject.toml` | — | 3.11+ |
| R9.02 | Pandas / NumPy / SciPy | ✅ | `pyproject.toml` | — | — |
| R9.03 | Polars | ⏳ | — | — | Se añadirá cuando haya volumen que lo justifique |
| R9.04 | Statsmodels | ⏳ | — | — | Previsto para tests de series temporales / regresiones |
| R9.05 | scikit-learn (ML) | ⏳ | — | — | Con R10.13–R10.14 |
| R9.06 | Optuna | ⏳ | — | — | Optimización con control de overfitting |
| R9.07 | DuckDB + PyArrow / Parquet | ✅ | `packages/aqt/data/store.py::ParquetStore` | `tests/test_data.py::test_parquet_roundtrip` | — |
| R9.08 | Backtester por arrays para investigación masiva | 🟡 | `packages/aqt/backtest/engine.py::run_backtest` | `tests/test_backtest.py::test_entry_next_open_and_stop_same_bar` | Bucle NumPy; falta acelerar (numba/vectorbt) para decenas de miles de variantes |
| R9.09 | Framework sencillo como validación secundaria | ⏳ | — | — | — |
| R9.10 | Histórico masivo en Parquet, no en Postgres | ✅ | `packages/aqt/data/store.py::ParquetStore` | `tests/test_data.py::test_parquet_roundtrip` | — |
| R9.11 | Supabase para metadatos, estrategias, resultados, experimentos | 🟡 | `supabase/migrations/20261001000000_initial_schema.sql` | — | Tablas creadas; falta persistir desde Python |
| R9.12 | Descarga de datos históricos reales | ⏳ | `packages/aqt/data/adapters.py::MarketDataAdapter` | — | Sólo sintético/CSV/Parquet local; falta adaptador de proveedor |

## §10 Catálogo de estrategias

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R10.01 | Candlestick patterns | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | Familia `candlestick` |
| R10.02 | Trend following | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.03 | Momentum | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.04 | Mean reversion | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.05 | Breakouts | ✅ | `packages/aqt/strategies/catalog.py::CATALOG` | `tests/test_dsl.py::test_catalog_renders_on_features` | — |
| R10.06 | Volatility | ⏳ | — | — | — |
| R10.07 | Volume | ⏳ | — | — | Feature `volume_ratio` ya disponible |
| R10.08 | Relative strength | ⏳ | — | — | Requiere multi-símbolo (R11.19) |
| R10.09 | Pairs | ⏳ | — | — | Requiere multi-símbolo |
| R10.10 | Cross-sectional signals | ⏳ | — | — | Requiere multi-símbolo |
| R10.11 | Market regime | ⏳ | `packages/aqt/regime/classifier.py::RegimeClassifier` | — | Features de régimen disponibles; falta familia que opere con ellas |
| R10.12 | Multi-factor | ⏳ | — | — | — |
| R10.13 | ML classifiers | ⏳ | — | — | — |
| R10.14 | ML regressors | ⏳ | — | — | — |
| R10.15 | Sentiment / news / macro (posterior) | ⏳ | — | — | Fase posterior |
| R10.16 | Sin HFT | 🚫 | `packages/aqt/backtest/engine.py::run_backtest` | — | Sólo barras; ningún componente de baja latencia |
| R10.17 | Sin opciones ni futuros | 🚫 | `packages/aqt/brokers/base.py::Instrument` | — | Sólo acciones/ETF |
| R10.18 | Sin margen | 🚫 | `packages/aqt/risk/profile.py::AbsoluteLimits` | `tests/test_risk.py::test_property_approved_orders_never_exceed_limits` | `allow_margin=False`; nocional ≤ equity |
| R10.19 | Sin apalancamiento | 🚫 | `packages/aqt/risk/profile.py::AbsoluteLimits` | `tests/test_risk.py::test_manual_profile_cannot_breach_absolute_limits` | `max_portfolio_exposure ≤ 1.0` |
| R10.20 | Sin short selling | 🚫 | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_sell_exits_allowed_shorts_forbidden` | Además backtester long-only y `SimulatedBroker` rechaza cortos |
| R10.21 | Sin Reinforcement Learning con dinero real | 🚫 | — | — | No existe ningún componente RL |
| R10.22 | Sin decisiones directas de LLM | 🚫 | `services/ai_analyst/README.md` | — | Ningún módulo de `packages/aqt` importa un cliente LLM |

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
| R11.15 | Market breadth | ⏳ | — | — | Requiere universo multi-símbolo |
| R11.16 | Correlación | ⏳ | — | — | Requiere benchmark |
| R11.17 | Beta | ⏳ | — | — | Requiere benchmark |
| R11.18 | Relative strength | ⏳ | — | — | Requiere benchmark |
| R11.19 | Soporte multi-símbolo / benchmark en el Feature Engine | ⏳ | — | — | Prerrequisito de R11.15–R11.18 y R10.08–R10.10 |
| R11.20 | Régimen de mercado como feature | ✅ | `packages/aqt/regime/classifier.py::RegimeClassifier` | `tests/test_indicators.py::test_feature_engine_columns` | tendencia × volatilidad |
| R11.21 | Geometría de velas (body, sombras, body/range, close_position) | ✅ | `packages/aqt/indicators/core.py::candle_geometry` | `tests/test_indicators.py::test_candle_geometry_ranges` | — |
| R11.22 | Patrones con nombre derivados de la geometría | ✅ | `packages/aqt/features/engine.py::candlestick_patterns` | `tests/test_dsl.py::test_catalog_renders_on_features` | engulfing, hammer, shooting star, doji |
| R11.23 | Descubrimiento de patrones sin nombre tradicional | ⏳ | — | — | Geometría disponible; falta búsqueda automática (R30.12) |
| R11.24 | Features causales (sin look-ahead) | ✅ | `packages/aqt/features/engine.py::FeatureEngine` | `tests/test_indicators.py::test_features_have_no_look_ahead` | — |

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
| R12.15 | Evitar data snooping | 🟡 | `packages/aqt/statistics/multiple_testing.py::benjamini_hochberg` | `tests/test_statistics.py::test_fdr_controls_false_discoveries_under_null` | FDR por estudio; falta registro global de hipótesis probadas |
| R12.16 | Control de multiple hypothesis testing (FDR) | ✅ | `packages/aqt/statistics/multiple_testing.py::benjamini_hochberg` | `tests/test_statistics.py::test_benjamini_hochberg` | — |
| R12.17 | FDR global sobre miles de hipótesis (todo el universo) | ⏳ | — | — | Hoy por estrategia × símbolo |

## §13 Bayesian Evidence Engine

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R13.01 | Distinguir 95/100 de 9.500/10.000 | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | — |
| R13.02 | Distribuciones posteriores | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | Win rate; falta posterior del EV |
| R13.03 | Intervalos creíbles | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | — |
| R13.04 | Actualización bayesiana | ✅ | `packages/aqt/statistics/bayes.py::BetaPosterior` | `tests/test_statistics.py::test_bayes_evidence_scales_with_sample` | `update_one` |
| R13.05 | Cada nueva operación real/paper actualiza la evidencia | ⏳ | — | — | Requiere trader + persistencia |

## §14 Champion / Challenger

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R14.01 | Estados Champion / Challenger | 🟡 | `supabase/migrations/20261001000000_initial_schema.sql` | — | `strategies.status`; falta lógica |
| R14.02 | La IA no despliega cambios directamente | 🟡 | `services/ai_analyst/README.md` | — | Por diseño; forzar con roles al implementar el analista |
| R14.03 | Pipeline Backtest → OOS → WF → costes | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Veredicto `CHALLENGER_CANDIDATE` |
| R14.04 | Paper trading antes de promoción | ⏳ | — | — | Iteración 2 |
| R14.05 | Comparación con el Champion | ⏳ | — | — | — |
| R14.06 | Promoción auditada | 🟡 | `supabase/migrations/20261001000000_initial_schema.sql` | — | Tabla `strategy_promotions`; falta flujo |

## §15 Shadow Portfolios

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R15.01 | Cartera real (Champion) + carteras shadow paralelas | ⏳ | `packages/aqt/brokers/simulated.py::SimulatedBroker` | — | Broker simulado reutilizable como cartera shadow |
| R15.02 | Benchmark Buy & Hold | ⏳ | — | — | — |
| R15.03 | Benchmark Cash | ⏳ | — | — | — |
| R15.04 | Comparación continua | ⏳ | — | — | `paper_runs` en el esquema |

## §16 Counterfactual Learning

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R16.01 | Guardar lo ocurrido y la alternativa contraria | 🟡 | `supabase/migrations/20261001000000_initial_schema.sql` | — | Columna `signals.counterfactual`; falta cálculo |
| R16.02 | Aprender de oportunidades rechazadas (NO BUY) | ⏳ | — | — | — |

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
| R17.14 | Trading-hours validation | 🟡 | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | Usa `MarketState.market_open`; falta calendario de mercado real |
| R17.15 | API health validation | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.16 | Portfolio reconciliation | 🟡 | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | Bloquea si `reconciled=False`; falta el proceso de reconciliación con el broker |
| R17.17 | Kill switch | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_sell_exits_allowed_shorts_forbidden` | También flag `GLOBAL_KILL_SWITCH`: `tests/test_config.py::test_invalid_mode_and_kill_switch` |
| R17.18 | Cualquier fallo → TRADE REJECTED | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | — |
| R17.19 | Salida APPROVE / REJECT / ADJUST_SIZE | ✅ | `packages/aqt/risk/engine.py::RiskAction` | `tests/test_risk.py::test_adjust_size_when_position_cap_binds` | — |

## §18 Cost awareness

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R18.01 | Gross edge − fees − FX − spread − slippage = net edge | ✅ | `packages/aqt/backtest/costs.py::CostModel` | `tests/test_backtest.py::test_costs_reduce_returns_and_equity_matches_trades` | — |
| R18.02 | Descartar estrategias que sólo funcionan antes de costes | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Check `edge_after_costs` |
| R18.03 | Filtro económico por operación en vivo | ✅ | `packages/aqt/risk/engine.py::RiskEngine` | `tests/test_risk.py::test_each_check_rejects` | `min_expected_net_edge` |
| R18.04 | Comisiones fijas relevantes con cuentas pequeñas | ✅ | `packages/aqt/backtest/costs.py::CostModel` | `tests/test_backtest.py::test_cost_model_validation` | Coste calculado sobre el nocional real |
| R18.05 | Tarifas reales de Trading 212 (FX 0,15 %, etc.) verificadas | ⏳ | `packages/aqt/backtest/costs.py::CostModel` | — | Valores por defecto estimados; validar antes de Live |

## §19 AI Analyst

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R19.01 | El LLM nunca envía órdenes | 🟡 | `services/ai_analyst/README.md` | — | Por diseño; forzar con credenciales/roles separados al implementarlo |
| R19.02 | Análisis de operaciones, errores, régimen, anomalías, degradación | ⏳ | — | — | Iteración 3 |
| R19.03 | Generación de hipótesis y Challengers | ⏳ | — | — | — |
| R19.04 | Literatura, noticias, macro, lecciones | ⏳ | — | — | — |
| R19.05 | Salida estructurada | 🟡 | `supabase/migrations/20261001000000_initial_schema.sql` | — | Tablas `ai_reviews`, `ai_hypotheses`, `lessons` |
| R19.06 | El Research Engine confirma o rechaza las hipótesis | ⏳ | — | — | — |

## §20 Memoria (Supabase)

Todas las tablas están creadas en el proyecto "Autonomous trading" con RLS, marcador `aqt`,
lectura para `authenticated`, sin acceso `anon` y escritura sólo vía `service_role`.

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R20.01 | Tablas de §20 creadas (strategies … configuration) | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | 22 tablas aplicadas y verificadas vía MCP |
| R20.02 | RLS en todas las tablas | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | — |
| R20.03 | Privilegios mínimos (anon sin acceso, dashboard sólo lectura + slider/kill switch) | ✅ | `supabase/migrations/20261001010000_harden_privileges.sql` | — | Advisor de seguridad de Supabase sin avisos |
| R20.04 | Auditoría de cambios de configuración | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | Trigger → `config_audit_log` |
| R20.05 | Persistencia desde Python (cliente Supabase) | ⏳ | — | — | Próximo paso: guardar experimentos y backtests |
| R20.06 | La memoria del LLM no es almacenamiento principal | ✅ | `supabase/migrations/20261001000000_initial_schema.sql` | — | — |

## §21–22 Arquitectura y uso de Lovable

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R21.01 | Research / Trading / Risk en Python | 🟡 | `packages/aqt` | — | Research y Risk ✅; Trading ⏳ |
| R21.02 | Historical data en Parquet + DuckDB | ✅ | `packages/aqt/data/store.py::ParquetStore` | `tests/test_data.py::test_parquet_roundtrip` | — |
| R21.03 | Supabase PostgreSQL | ✅ | `supabase/migrations` | — | — |
| R21.04 | Worker en Railway | ⏳ | — | — | — |
| R21.05 | Frontend Lovable / Next.js en Vercel | ⏳ | `apps/dashboard/README.md` | — | — |
| R21.06 | BrokerAdapter abstracto | ✅ | `packages/aqt/brokers/base.py::BrokerAdapter` | `tests/test_brokers.py::test_simulated_buy_sell_cycle` | — |
| R21.07 | Trading212Adapter | ⏳ | `packages/aqt/brokers/trading212.py::Trading212Broker` | `tests/test_brokers.py::test_trading212_guardrails` | Stub con guardarraíles |
| R21.08 | IBKRAdapter (futuro) | ⏳ | — | — | — |
| R21.09 | MarketDataAdapter intercambiable | ✅ | `packages/aqt/data/adapters.py::MarketDataAdapter` | `tests/test_data.py::test_csv_adapter` | — |
| R22.01 | El núcleo no se implementa en Lovable | ✅ | `apps/dashboard/README.md` | — | — |
| R22.02 | El frontend nunca tiene claves del broker | ✅ | `.env.example` | — | Sólo backend; dashboard usa anon key + Auth |

## §23–25 Entorno y runtime

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R23.01 | Monorepo con la estructura recomendada | ✅ | `packages/aqt`, `services`, `apps/dashboard`, `supabase/migrations`, `docs`, `infra` | — | Paquetes como subpaquetes de `aqt` |
| R23.02 | Ramas main / develop | ⏳ | — | — | Hoy se trabaja en rama de feature; crear `develop` |
| R23.03 | CI con lint, tipos, tests y escaneo de secretos | ✅ | `.github/workflows/ci.yml` | — | ruff, mypy, pytest, gitleaks |
| R25.01 | El bot es un servicio Python (no vive en el agente) | ⏳ | — | — | — |
| R25.02 | Cron: scanner, daily review, research, AI review, reconciliación | ⏳ | — | — | — |
| R25.03 | Sin LLM por tick | ✅ | `services/ai_analyst/README.md` | — | Ningún camino de ejecución llama a un LLM |

## §26–29 Broker, OpenAI y cuentas

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R26.01 | Trading 212: entornos Demo y Live separados | ✅ | `packages/aqt/brokers/trading212.py::Trading212Broker` | `tests/test_brokers.py::test_trading212_guardrails` | URLs demo/live según modo |
| R26.02 | Credenciales API key + secret desde secretos, nunca en código | ✅ | `.env.example` | `tests/test_brokers.py::test_trading212_guardrails` | `repr` no filtra secretos |
| R26.03 | Restricción de claves por IP | ⏳ | — | — | Manual en Trading 212 al crear las claves |
| R26.04 | Órdenes fraccionarias | ✅ | `packages/aqt/risk/models.py::MarketState` | `tests/test_risk.py::test_small_account_100_eur` | `quantity_step` |
| R26.05 | Revalidar limitaciones de la API beta antes de Live | ⏳ | — | — | — |
| R28.01 | Proyecto OpenAI con key propia, presupuesto y logging | ⏳ | `.env.example` | — | Manual (usuario) |
| R28.02 | Modelo barato frecuente / potente para research | ⏳ | `.env.example` | — | `OPENAI_MODEL_CHEAP` / `OPENAI_MODEL_STRONG` |
| R29.01 | Cuenta GitHub | ✅ | — | — | — |
| R29.02 | Cuenta Supabase | ✅ | — | — | Proyecto "Autonomous trading" |
| R29.03 | Cuenta Railway | ⏳ | — | — | — |
| R29.04 | Cuenta Trading 212 Invest (Demo) | ⏳ | — | — | — |
| R29.05 | Cuenta OpenAI Platform | ⏳ | — | — | — |
| R29.06 | Cuenta Vercel | ⏳ | — | — | — |
| R29.07 | Cuenta Lovable | ⏳ | — | — | — |

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
| R30.09 | Paso 9 — Paper Trader | ⏳ | `services/trader/README.md` | — | Iteración 2 |
| R30.10 | Paso 10 — Shadow Engine | ⏳ | — | — | Iteración 3 |
| R30.11 | Paso 11 — AI Analyst | ⏳ | — | — | Iteración 3 |
| R30.12 | Paso 12 — Autonomous Research Loop | ⏳ | — | — | Iteración 4 |
| R30.13 | Paso 13 — Dashboard | ⏳ | `apps/dashboard/README.md` | — | — |
| R30.14 | Paso 14 — Deploy | ⏳ | — | — | — |
| R30.15 | Paso 15 — Seguridad: entornos y doble flag LIVE | ✅ | `packages/aqt/common/config.py::load_settings` | `tests/test_config.py::test_live_requires_both_flags` | — |
| R30.16 | Paso 15 — Claves distintas por entorno | 🟡 | `.env.example` | — | Variables separadas demo/live; falta gestor de secretos |
| R30.17 | Paso 15 — Global kill switch en dashboard | 🟡 | `supabase/migrations/20261001010000_harden_privileges.sql` | — | Columna editable y auditada; falta UI y lectura en el trader |
| R30.18 | Paso 16 — Go-live gate | ⏳ | — | — | Ver §31 |

## §31 Go-live gate y configuración LIVE inicial

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R31.01 | Evidencia out-of-sample | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_random_walk_is_not_promoted` | Herramienta lista; falta evidencia con datos reales |
| R31.02 | EV positivo después de costes | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Ídem |
| R31.03 | Drawdown dentro del límite | ✅ | `packages/aqt/research/pipeline.py::run_research` | `tests/test_research.py::test_pipeline_is_reproducible` | Check `drawdown_within_limit` (Monte Carlo) |
| R31.04 | Estabilidad por régimen | 🟡 | `packages/aqt/statistics/regimes.py::metrics_by_regime` | — | Se reporta; aún no es criterio del veredicto |
| R31.05 | Paper trading consistente | ⏳ | — | — | — |
| R31.06 | Ausencia de errores de reconciliación | ⏳ | — | — | — |
| R31.07 | Kill switch probado end-to-end | ⏳ | — | — | Probado en Risk Engine; falta prueba con broker |
| R31.08 | Recuperación del broker probada | ⏳ | — | — | — |
| R31.09 | Gate automatizado (checklist ejecutable) | ⏳ | — | — | — |
| R31.10 | Config LIVE inicial: 100 €, límites estrictos, pocas posiciones | ✅ | `packages/aqt/risk/profile.py::RiskProfile` | `tests/test_risk.py::test_small_account_100_eur` | `configuration.aggressiveness` por defecto 20 |

## §32–34 Escalabilidad, métrica y objetivo final

| ID | Requisito | Estado | Implementación | Tests | Falta / notas |
|---|---|---|---|---|---|
| R32.01 | Nada depende de que el capital sea 100 € | ✅ | `packages/aqt/sizing/engine.py::PositionSizingEngine` | `tests/test_sizing.py::test_scales_with_capital` | — |
| R33.01 | Métrica principal: risk-adjusted OOS expectancy | ✅ | `packages/aqt/research/report.py::render_markdown` | `tests/test_research.py::test_report_files` | EV OOS, IC, Sharpe/Sortino OOS en el informe |
| R34.01 | Ciclo autónomo completo market data → … → new research | ⏳ | — | — | Suma de todos los pendientes |

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
