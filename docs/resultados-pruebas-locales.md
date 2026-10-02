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
| 3 research 1d | EN CURSO | > 45 min (1.ª vez) | Lo ejecuta el propio trader al arrancar (ciclo n.º 3, desde las 17:47; incluye 15min, 1h y 1d con noticias). Titulares: 3 años × 10 acciones descargados. Velas de 1 min: SPY, QQQ, AAPL completas (5 años), el resto en curso |
| 4 research 1h | EN CURSO | | Incluido en el mismo ciclo n.º 3 |
| 5 trader + dashboard | OK | 10 min | Con `--broker alpaca` (cuenta paper). Consola: «PAPER trader (stocks, orders -> Alpaca PAPER account)», subcuenta de 10.000 USD sin margen. Feed IEX conectado (> 900.000 eventos), panel «Noticias del día» con titulares enlazados, `/api/news`: sondeo activo, 1.778 titulares, sin errores. Kill switch y pausa: activar y desactivar funcionan (la puerta a real marca el kill switch como probado, 5/10). Sin errores en la consola del navegador. No se paró con Ctrl+C: se dejó funcionando a petición del usuario |
| 6 menú | OK | — | Opción «📰 Noticias del día» presente; por defecto genera `news --market stocks --dry-run --no-force` |

## Errores (texto completo)

Ninguno hasta ahora.

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

## Estado al subir este informe (18:35, hora de España)

Los pasos 3 y 4 siguen en curso: la primera descarga de 5 años de velas de 1 minuto está limitada
por Alpaca a 200 peticiones por minuto. Los resultados (hipótesis por escala, supervivientes `*`,
checks que fallan) se añadirán cuando termine el ciclo n.º 3.
