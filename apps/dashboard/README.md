# Dashboard (pendiente)

Se construirá con **Lovable / Next.js** y se desplegará en **Vercel**.

Pantallas: Overview, Portfolio, Trades, Signals, Research Lab, Strategy Explorer,
Champion / Challengers, Risk (slider de agresividad), AI Journal, Lessons, Experiments,
System Health, Settings, **Global Kill Switch**.

Reglas:
- Usa sólo la *anon/publishable key* de Supabase y Auth; nunca claves del broker ni `service_role`.
- Lectura de todas las tablas vía RLS; escritura únicamente de `configuration.aggressiveness` y
  `configuration.kill_switch` (auditadas). No puede activar LIVE.
- No contiene lógica de backtesting, estadística, riesgo ni ejecución.
