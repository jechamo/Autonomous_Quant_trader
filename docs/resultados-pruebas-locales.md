# Resultados de las pruebas en local — 2026-10-02

Ejecutadas por Claude Code en el PC del usuario siguiendo [`pruebas-locales.md`](pruebas-locales.md)
sobre la rama `claude/jolly-turing-zitp3y` (Windows 11, viernes, mercado de EE. UU. abierto).
Claves de Alpaca **paper** y de OpenAI presentes en `.env` (comprobado sin mostrar valores);
`TRADING_MODE=DEV`, `LIVE_TRADING_ENABLED=false`.

| Paso | Resultado | Tiempo | Notas |
|---|---|---|---|
| 0 Preparación / make check | OK | 6 min 10 s | 265 tests en verde, cobertura 96 %; ruff, formato y mypy limpios |
| 1 news --dry-run | OK | 7 s | Fecha NY 2026-10-02 (viernes, 11:42), `us_market_open_today: true`, 120 titulares seleccionados de 496 descargados, todos con `id`, `published_new_york`, `symbols`, `kind`, `headline`; los 42 primeros tocan el universo. Features `news_ratio`, `news_1d`, `rsi_2`, `down_streak` presentes |
| 2 news (IA) | OK | 43 s | gpt-6-sol. 8 eventos (importancia 2–5), watchlist de 7 valores, 0 descartados, 1 hipótesis aceptada y 1 rechazada (nombre de 44 caracteres > 40). La 2.ª ejecución se salta: «ya hay un resumen para 2026-10-02» |
| 3 research 1d (1.ª / 2.ª vez) | OK | 1 h 31 min / 45 s | 1.ª vez: dentro del ciclo n.º 3 del trader (15min, 1h y 1d; 17:47–19:18), casi todo descarga de 5 años de velas de 1 min. 2.ª vez (`--timeframes 1d --no-analyst`, ciclo n.º 4): 45 s con caché. `news: 74630 headlines over 1095 days`. 1d: 118 hipótesis, 0 sobreviven al FDR global, 0 candidatas, 0 promovidas. Mejores agrupadas `*`: `trend_follow` +3,25 % (76 fechas, p = 0,09), `earnings_gap_drift` +3,59 % (11), `breadth_dip` +3,16 % (10), `near_52w_high` +2,77 % (35), `xs_momentum_long` +2,20 % (71); todas REJECTED. Resultados idénticos entre ciclos (reproducible) |
| 4 research 1h | OK | (en el ciclo n.º 3) | 1.110 hipótesis a 1h (y 1.790 a 15min); entre las familias probadas están `streak_reversion`, `rsi2_reversion`, `news_drift`, `quiet_drop_reversal` y `earnings_gap_drift`. Ciclo completo: 3.022 hipótesis, 2 sobreviven al FDR global, 0 candidatas. Mejores 1h por acción: MSFT `earnings_gap_drift` +6,7 % y AMZN `news_drift` +5,7 %, pero con 1 operación fuera de muestra; META `trend_follow` +3,0 % (8). Todas REJECTED |
| 5 trader + dashboard | OK | 10 min | Con `--broker alpaca` (cuenta paper). Consola: «PAPER trader (stocks, orders -> Alpaca PAPER account)», subcuenta de 10.000 USD sin margen. Feed IEX conectado (> 900.000 eventos), panel «Noticias del día» con titulares enlazados, `/api/news`: sondeo activo, 1.778 titulares, sin errores. Kill switch y pausa: activar y desactivar funcionan (la puerta a real marca el kill switch como probado, 5/10). Sin errores en la consola del navegador. No se paró con Ctrl+C: se dejó funcionando a petición del usuario |
| 6 menú | OK | — | Opción «📰 Noticias del día» presente; por defecto genera `news --market stocks --dry-run --no-force` |

## Errores (texto completo)

Ningún error. Un aviso no bloqueante en cada research con noticias:

```
packagesqt
ewslpaca.py:130: UserWarning: Converting to Period representation will drop timezone information.
  this_month = pd.Timestamp.now(tz="UTC").to_period("M")
packagesqt
ewslpaca.py:135: UserWarning: Converting to Period representation will drop timezone information.
```

## Reglas que sobrevivieron

Ninguna llegó a candidata. Las que más se acercan son agrupadas en 1d:

| Familia | Símbolo | EV fuera de muestra | Fechas | Checks que fallan |
|---|---|---|---|---|
| `trend_follow` | `*` | +3,25 % | 76 | significación OOS (p = 0,09), FDR in-sample, drawdown |
| `near_52w_high` | `*` | +2,77 % | 35 | significación OOS (p = 0,14), FDR in-sample, drawdown |
| `xs_momentum_long` | `*` | +2,20 % | 71 | — (no pasa el FDR global) |
| `earnings_gap_drift` | `*` | +3,59 % | 11 | muestra OOS insuficiente, significación, estabilidad |
| `breadth_dip` | `*` | +3,16 % | 10 | muestra OOS insuficiente, significación |

Las ideas de la IA examinadas en el ciclo n.º 3 se rechazaron: `ai_friday_selloff_weekend_rebound`
(`*`, +0,78 %, 54 fechas), `ai_unexplained_volume_accumulation` (`*`, +0,19 %, 37) y
`ai_continuacion_tras_ruptura_con_noticias` (AMZN, +1,26 %, 7).

## Observaciones sobre «Noticias del día»

- Contrastadas 3 cifras con su titular original y coinciden: entregas de Tesla 486.532 frente a
  456.896 estimadas; posible sanción a Meta de hasta 40.000 millones en Nuevo México; 29.000
  empleos creados en septiembre. Los importes potenciales se presentan como potenciales.
- El resumen es útil y prudente (distingue «posible», «no confirmado», «no equivale a una
  aprobación»).

## Notas sobre la guía de pruebas

- La comprobación de claves del paso 0 usa `dotenv`, que no está instalado; se usó
  `aqt.common.config.load_dotenv` y los alias de claves de `aqt.stream.alpaca` (el usuario usa
  `ALPACA_KEY_PAPER`; el código acepta ambos nombres).
- `news --dry-run` recorta la salida a 8.000 caracteres, así que el JSON impreso no es válido
  completo; la comprobación del paso 1 se hizo leyendo el contexto entero con el mismo código.
- El paso 5 se hizo con `--broker alpaca` (no `local`) porque el usuario pidió expresamente dejar
  funcionando su cuenta Alpaca **paper**.


## Conclusión

Todo lo añadido en la rama funciona con datos y claves reales: titulares, «Noticias del día» sin
invenciones, research agrupado con noticias, dashboard y menú. Ninguna regla supera todavía todos
los exámenes, así que el sistema, correctamente, no opera en paper. La prueba agrupada sí acerca
reglas diarias a la significación (tendencia: 76 fechas fuera de muestra, p = 0,09). El trader
Alpaca paper queda funcionando con research cada 6 horas.
