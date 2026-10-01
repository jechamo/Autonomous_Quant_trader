# Dashboard

## Local (disponible)

`apps/dashboard/local/` es el frontal del trader en streaming. Lo sirve el propio trader:

```bash
uv run python -m services.trader run      # abre http://127.0.0.1:8000
```

HTML + JS sin build (gráficos con TradingView Lightweight Charts desde unpkg). Recibe el estado
por WebSocket cada 0,5 s: velas en vivo con entradas/salidas y stop/objetivo, flujo de órdenes,
equity, evidencia por estrategia (incluidas las señales bloqueadas por coste), decisiones del
Risk Engine con sus motivos y operaciones paper / en sombra. Controles: **kill switch**, pausa,
cerrar todo y slider de agresividad (siempre recortado por `AbsoluteLimits`).

## Desplegado (pendiente)

Se construirá con **Lovable / Next.js** y se desplegará en **Vercel**.

Pantallas: Overview, Portfolio, Trades, Signals, Research Lab, Strategy Explorer,
Champion / Challengers, Risk (slider de agresividad), AI Journal, Lessons, Experiments,
System Health, Settings, **Global Kill Switch**.

Reglas:
- Usa sólo la *anon/publishable key* de Supabase y Auth; nunca claves del broker ni `service_role`.
- Lectura de todas las tablas vía RLS; escritura únicamente de `configuration.aggressiveness` y
  `configuration.kill_switch` (auditadas). No puede activar LIVE.
- No contiene lógica de backtesting, estadística, riesgo ni ejecución.
