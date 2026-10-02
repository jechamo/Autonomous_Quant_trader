# Autonomous Quant Trader — guía para agentes

Sistema de trading cuantitativo. PRD: `docs/PRD.md`. Estado requisito a requisito:
`docs/prd-traceability.md`. Arquitectura: `docs/architecture.md`. Pasos: `docs/roadmap.md`.

## Comandos
- `uv sync` — instalar dependencias.
- `make check` — ruff + format check + mypy + pytest con cobertura (debe quedar verde antes de commit).
- `uv run python -m services.research.cli run --strategy momentum` — research reproducible.
- `uv run python tests/test_traceability.py` — regenera el resumen de la matriz de trazabilidad.
- `AQT.cmd` / `uv run python -m services.launcher` — menú de arranque (Textual) con todos los modos.
- `uv run python -m services.trader run` — trader en streaming (PAPER, Binance) + dashboard local
  en `http://127.0.0.1:8000` con el Research Lab programado; `--market stocks` usa Alpaca (claves en
  `.env`). `research` lanza un ciclo del lab; `simulate [--learn]` reproduce la historia real;
  `news [--dry-run]` genera «Noticias del día» (titulares de Alpaca + OpenAI).
- Estudio de reglas (qué se prueba y por qué): `docs/estudio-reglas.md`.
- Pruebas con datos reales pendientes (para ejecutar en local): `docs/pruebas-locales.md`.
- Contexto de la sesión que añadió estudio, noticias y prueba agrupada: `docs/sesion-2026-10-02.md`.

## Regla obligatoria: matriz de trazabilidad
Todo cambio que implemente, modifique o elimine algo relacionado con un requisito del PRD
**actualiza `docs/prd-traceability.md` en el mismo commit**:
1. estado, implementación (`ruta.py::Símbolo`), tests (`tests/x.py::test_nombre`) y notas de la fila;
2. filas nuevas con IDs nuevos (nunca reutilizar ni renumerar);
3. regenerar el resumen y actualizar la fecha de *Última actualización*;
4. si cambia un paso de la hoja de ruta, actualizar también `docs/roadmap.md`;
5. citar los IDs afectados en el mensaje de commit (p. ej. `R17.14`).
`tests/test_traceability.py` falla en CI si una referencia no existe o el resumen no cuadra.

## Invariantes que no se negocian
- Ningún LLM decide ni envía órdenes; el AI Analyst no tiene acceso a `place_order`, secretos del
  broker ni escritura de configuración de riesgo.
- Toda orden pasa por `aqt.risk.RiskEngine`; los límites de `AbsoluteLimits` no se relajan
  (sin cortos, sin margen, sin apalancamiento, riesgo/trade ≤ 2 %).
- Features causales; el backtester ejecuta en la apertura siguiente. No introducir look-ahead.
- LIVE exige `TRADING_MODE=LIVE` y `LIVE_TRADING_ENABLED=true`. Nunca secretos en el repo.
- Risk/sizing con cobertura ≥ 95 % (gate en CI).

## Supabase
Proyecto "Autonomous trading" (`nzeuzxtpqrsvyvpxaugz`). Comparte `public` con tablas ajenas
(`audit_log`, `categories`, `jobs`, `system_settings`, `tool_definitions`, `tool_versions`):
no tocarlas. Nuestras tablas llevan el comentario `aqt`. Cambios de esquema siempre como nueva
migración idempotente en `supabase/migrations/`, validada en Postgres local antes de aplicarla, y
después revisar `get_advisors` (security).

## Convenciones
- Código, identificadores y commits en inglés; documentación de producto en español.
- Python 3.11, ruff (line-length 100), mypy; tests en `tests/` con datos sintéticos deterministas.
