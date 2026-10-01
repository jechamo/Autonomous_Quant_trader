# AI Analyst

Implementado en [`packages/aqt/analyst`](../../packages/aqt/analyst) (cliente OpenAI + hipótesis);
se usa desde `services/trader`:

```bash
uv run python -m services.trader analyst --dry-run   # qué leería (sin llamar a la API)
uv run python -m services.trader analyst             # una ronda de hipótesis
uv run python -m services.trader research            # pregunta al analista y examina sus hipótesis
```

Hecho: `hypothesis_generator` (hipótesis en el DSL con *Claim / Evidence / Suggested experiment*,
validadas y examinadas por el Research Lab). Pendiente: `daily_trade_review`,
`strategy_degradation_analysis`, `anomaly_detection`, `weekly_research_review`.

Restricciones (por diseño y verificadas por test):
- Sin acceso a secretos del broker, a `place_order()` ni a escritura de la configuración de
  riesgo: el paquete no importa `aqt.brokers`, `aqt.risk`, el motor ni `services`.
- Sólo produce información **estructurada** (tabla `hypotheses`; en Supabase `ai_hypotheses`
  cuando se sincronice).
- El Research Lab es quien confirma o rechaza cada hipótesis, dentro del mismo FDR global.
- Nunca se llama al LLM por tick de mercado: una vez por ciclo de research (cada 6 h) con un
  máximo de llamadas diarias. Modelo: `OPENAI_MODEL_STRONG`, si no `OPENAI_MODEL_CHEAP`, si no
  `gpt-5-mini`. Fija un presupuesto mensual en OpenAI Platform.
