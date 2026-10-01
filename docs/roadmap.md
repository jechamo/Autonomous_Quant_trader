# Roadmap

Detalle requisito por requisito en [`prd-traceability.md`](prd-traceability.md).

| Paso | Descripción | Estado |
|---|---|---|
| 1 | Repositorio, CI, tests, `.env.example`, exclusión de secretos | ✅ iteración 1 |
| 2 | Proyecto Supabase: esquema, RLS, auditoría de configuración | 🟡 esquema + hardening aplicados en «Autonomous trading» (advisor de seguridad limpio); faltan Vault, Storage y Auth |
| 3 | Research Engine + CLI con informe reproducible | ✅ |
| 4 | Strategy DSL | ✅ |
| 5 | Statistical Validation Engine | ✅ (OOS, WF, purged CV, Bayes, MC, FDR, costes, régimen) |
| 6 | Risk Engine aislado, alta cobertura | ✅ (≥95 % exigido en CI) |
| 7 | Cuenta Demo Trading 212 + credenciales en el gestor de secretos | ⏳ manual (usuario) |
| 8 | `Trading212Broker` real (demo) | ⏳ iteración 2 |
| 9 | Paper Trader: Signal → Risk → Broker, registrar todas las decisiones | ⏳ iteración 2 |
| 10 | Shadow Engine (Champion, Challengers, Buy & Hold, Cash) + counterfactuals | ⏳ iteración 3 |
| 11 | AI Analyst (OpenAI) con salida estructurada, sin acceso a órdenes | ⏳ iteración 3 |
| 12 | Autonomous Research Loop (Railway cron) | ⏳ iteración 4 |
| 13 | Dashboard Lovable | ⏳ |
| 14 | Deploy (Vercel / Supabase / Railway) | ⏳ |
| 15 | Seguridad: entornos DEV/PAPER/LIVE, kill switch global | 🟡 flags y kill switch en código y esquema |
| 16 | Go-live gate (100 €) | ⏳ |

## Próximos pasos técnicos sugeridos

- Persistir resultados del pipeline en Supabase (`experiments`, `backtests`, `walk_forward_runs`).
- Descarga de datos reales a Parquet (p. ej. proveedor gratuito vía `MarketDataAdapter`).
- Barrido multi-símbolo con FDR global sobre todo el universo de hipótesis.
- Probabilistic / Deflated Sharpe Ratio.
- Aceleración (numba / vectorbt) para barridos de decenas de miles de variantes.
