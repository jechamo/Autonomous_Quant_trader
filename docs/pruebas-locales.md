# Pruebas en local con datos reales (instrucciones para Claude Code)

**Para qué:** todo lo añadido en la rama `claude/jolly-turing-zitp3y` (estudio de reglas,
noticias reales, «Noticias del día», prueba agrupada) pasa 265 tests con datos sintéticos, pero
no se ha ejecutado con las claves reales de Alpaca y OpenAI. Este documento es para que un agente
(Claude Code en el PC del usuario) haga esas pruebas en orden y deje un informe.

**Cómo usarlo:** abre Claude Code en la carpeta del repositorio y dile:
«Lee `docs/pruebas-locales.md` y ejecútalo paso a paso».

**Contexto:** antes de empezar, lee [`sesion-2026-10-02.md`](sesion-2026-10-02.md): qué se
cambió en esta rama, por qué, y dónde mirar si algo falla.

## Reglas para el agente (obligatorias)

1. **Sólo PAPER.** No pongas `LIVE_TRADING_ENABLED=true` ni `TRADING_MODE=LIVE`, no uses claves
   de dinero real y no lances nada con `--broker alpaca` (eso envía órdenes a la cuenta paper;
   aquí basta con `--broker local`).
2. **Nunca muestres, copies ni escribas claves.** Comprueba que existen sin imprimir su valor.
3. **No cambies código** salvo que el usuario lo pida. Si algo falla, anótalo con el error y
   sigue con el siguiente paso si es independiente.
4. **Para y pregunta** si algún paso pide pagar, aceptar condiciones o tocar dinero real.
5. Apunta todo en `docs/resultados-pruebas-locales.md` (plantilla en el paso 7).
6. Los pasos 3 y 4 pueden tardar mucho la primera vez: avisa al usuario y déjalos correr.

## Paso 0 — Preparación

```bash
git fetch origin && git checkout claude/jolly-turing-zitp3y && git pull
uv sync
```
- Comprueba, **sin mostrar valores**, que `.env` define `ALPACA_API_KEY_ID`,
  `ALPACA_API_SECRET_KEY` (claves paper de Alpaca) y `OPENAI_API_KEY`. Por ejemplo:
  `uv run python -c "from dotenv import dotenv_values as d; v=d('.env'); print({k: bool(v.get(k)) for k in ['ALPACA_API_KEY_ID','ALPACA_API_SECRET_KEY','OPENAI_API_KEY']})"`
- Si falta alguna, para y díselo al usuario (cómo conseguirlas: `services/trader/README.md`).
- `make check` → debe terminar con todos los tests en verde. Anota el número de tests.

## Paso 1 — Titulares reales sin IA (gratis)

```bash
uv run python -m services.trader news --dry-run
```
Comprueba y anota:
- `today.date_new_york` es la fecha actual en Nueva York y `weekday` el día correcto.
- `us_market_open_today` es `true` un día de mercado, `false` en fin de semana o festivo
  (o `null` si no se pudo consultar).
- `headlines` trae titulares reales recientes, cada uno con `id`, `published_new_york`,
  `symbols`, `kind` y `headline`; los de AAPL, NVDA, TSLA… aparecen primero.
- `available_features` incluye `news_ratio`, `news_1d`, `rsi_2` y `down_streak`.

## Paso 2 — «Noticias del día» con IA (1 llamada a OpenAI, céntimos)

```bash
uv run python -m services.trader news
uv run python -m services.trader news      # la segunda debe saltarse
```
Comprueba y anota:
- La primera imprime `Noticias del día <fecha>` con un resumen en español, eventos con
  importancia, tipo, valores y por qué importan, y la watchlist.
- Si hay líneas `descartado: …`, cópialas: es lo que la IA dijo y no estaba en los titulares
  (que aparezca alguna es normal; muchas sería una señal de alarma).
- Las líneas `+ hypothesis …` son hipótesis que el lab examinará; las `- …` son rechazadas.
- La segunda ejecución dice `news briefing skipped: ya hay un resumen para <fecha>`.
- Contrasta 2 o 3 eventos con su titular original (que el resumen no exagere ni invente).

## Paso 3 — Research diario agrupado con noticias (puede tardar 30–90 min la primera vez)

```bash
uv run python -m services.trader research --market stocks --timeframes 1d --no-analyst
```
La primera vez descarga ~5 años de velas de 1 minuto y ~3 años de titulares por acción (el límite
de Alpaca es de 200 peticiones/min). Anota:
- Duración total.
- La línea `news: N headlines over 1095 days` (si dice `news rules: off`, anota el motivo).
- `hypotheses by timeframe: 1d …` y `… survive global FDR`, `candidates`, `promoted`.
- En `best out-of-sample pairs`, las filas con símbolo `*` son reglas agrupadas: anota familia,
  `OOS EV`, número de fechas (`trades`) y decisión.
- `failed checks`: qué pruebas fallan más.
- `live rules now`: si aparece alguna regla `…:*:…@1d`.

Después repítelo y anota la nueva duración (debe ser mucho menor gracias a la caché).

Que ninguna regla sobreviva es un resultado válido: el sistema no opera sin ventaja.

## Paso 4 — Research de 1 hora (por acción)

```bash
uv run python -m services.trader research --market stocks --timeframes 1h --no-analyst
```
Anota lo mismo que en el paso 3. Aquí las familias se prueban acción por acción (símbolos
normales, no `*`); deben aparecer `streak_reversion`, `rsi2_reversion`, `news_drift`,
`quiet_drop_reversal` y `earnings_gap_drift` entre las probadas.

## Paso 5 — Trader con dashboard (en horario de mercado: 15:30–22:00 hora de España)

```bash
uv run python -m services.trader run --market stocks --broker local --no-open
```
Abre el dashboard en la dirección que indique la consola (`http://127.0.0.1:8000` por defecto) y comprueba
durante 5–10 minutos:
- La consola dice `PAPER trader (stocks, local simulated fills)`.
- El panel **«Noticias del día»** muestra el resumen del paso 2, con enlaces a los titulares.
- `http://127.0.0.1:8000/api/news` → `poller.polls` aumenta cada minuto, `poller.headlines` > 0
  y `poller.last_error` vacío.
- En «Research Lab», si hay reglas con símbolo «todos (agrupada)», anótalas.
- Activa y desactiva el **kill switch** y la **pausa** desde el dashboard; anota que funcionan.
- Para con Ctrl+C y anota si se cerró limpio.

Fuera de horario de mercado, haz sólo las comprobaciones del panel y de `/api/news` y anótalo.

## Paso 6 — Menú de arranque

Ejecuta `AQT.cmd` (Windows) o `./aqt.sh`: comprueba que existe la opción «📰 Noticias del día»,
que con «Solo ver los titulares» activado el comando mostrado incluye `news --market stocks` y
`--dry-run`, y sal sin
lanzar nada más.

## Paso 7 — Informe

Crea `docs/resultados-pruebas-locales.md` con esta estructura y enséñaselo al usuario:

```markdown
# Resultados de las pruebas en local — <fecha>

| Paso | Resultado | Tiempo | Notas |
|---|---|---|---|
| 0 Preparación / make check | OK / fallo | | nº de tests |
| 1 news --dry-run | | | fecha NY, mercado abierto, nº titulares |
| 2 news (IA) | | | nº eventos, descartados, hipótesis |
| 3 research 1d (1ª / 2ª vez) | | | titulares, hipótesis, supervivientes `*` |
| 4 research 1h | | | |
| 5 trader + dashboard | | | sondeo, kill switch, pausa |
| 6 menú | | | |

## Errores (texto completo)
## Reglas que sobrevivieron (familia, símbolo o `*`, EV fuera de muestra, fechas/operaciones)
## Observaciones sobre «Noticias del día» (¿inventó algo? ¿resumen útil?)
```

**Qué no concluir:** que una regla sobreviva al research no significa que gane dinero. Primero
tiene que ganar evidencia en sombra y después pasar la puerta a real (`docs/roadmap.md`, paso
16). Nada de esto activa dinero real.

## Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `needs Alpaca keys` | Faltan claves en `.env` | Paso 0 |
| `news rules: off (…429…)` o descargas lentas | Límite de Alpaca (200 peticiones/min) | Esperar y repetir: la caché guarda lo descargado |
| `news briefing: off (set OPENAI_API_KEY…)` | Falta la clave de OpenAI | Añadirla a `.env` |
| `daily budget reached` | Ya se hicieron 6 llamadas a la IA hoy | Repetir mañana |
| Muy pocos datos o `only N bars` | Sin claves de Alpaca se usa Yahoo (~7 días) | Revisar claves |
| El dashboard no recibe precios | Mercado cerrado | Repetir en horario 15:30–22:00 (España) |
