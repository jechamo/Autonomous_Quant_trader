# AI Analyst (pendiente — iteración 3)

Funciones iniciales: `daily_trade_review`, `strategy_degradation_analysis`,
`hypothesis_generator`, `anomaly_detection`, `weekly_research_review`.

Restricciones (por diseño, no por convención):
- Sin acceso a secretos del broker, a `BrokerAdapter.place_order()` ni a escritura de la
  configuración de riesgo.
- Sólo produce información **estructurada** (`ai_reviews`, `ai_hypotheses`, `lessons`).
- El Research Engine es quien confirma o rechaza cada hipótesis.
- Nunca se llama al LLM por tick de mercado; modelo barato para análisis frecuentes y uno más
  potente para revisiones de research. Presupuesto mensual y logging en OpenAI Platform.
