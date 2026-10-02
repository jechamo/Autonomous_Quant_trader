# Estudio de reglas: qué merece la pena aplicar

**Fecha:** 2026-10-02 · **Implementación:** `packages/aqt/strategies/swing.py` (familias),
`packages/aqt/features/engine.py` y `packages/aqt/features/cross_section.py` (features).
**Trazabilidad:** R10.27–R10.32, R11.28–R11.30, R12.30.

## 1. Cómo leer este estudio

Este documento no dice «esta regla funciona». Dice **qué reglas merece la pena someter al Research
Lab** y por qué. Cada regla entra como hipótesis y pasa por el mismo camino que todas:

```
in-sample (barrido de parámetros) → FDR → out-of-sample congelado → walk-forward → Monte Carlo
→ FDR global (todas las hipótesis, símbolos y timeframes) → golden check en el motor real
→ challenger en sombra (evidencia forward desde cero) → Risk Engine
```

Si no sobrevive, no opera. Que una regla aparezca aquí sólo significa que tiene una razón económica
y evidencia publicada suficientes para gastar en ella parte del presupuesto de hipótesis (cada
variante nueva hace más estricto el FDR para todas las demás).

## 2. Criterios

1. **Evidencia publicada**, idealmente replicada fuera de la muestra original.
2. **Mecanismo económico** plausible (por qué alguien deja dinero en la mesa).
3. **Implementable sin cortos, margen ni apalancamiento** (límites absolutos del Risk Engine).
4. **Costes**: el movimiento esperado debe ser varias veces el coste (Alpaca ≈ 0 % de comisión
   más spread; Binance 0,10 % por lado). Por eso se descartan horizontes de minutos.
5. **Muestra**: debe disparar lo bastante a menudo para reunir ≥ 30 operaciones por símbolo.
6. **Expectativa honesta**: las anomalías publicadas rinden de media un 26 % menos fuera de la
   muestra original y un 58 % menos tras publicarse (McLean y Pontiff, 2016). Partimos de que
   la mayoría no sobrevivirá a costes.

## 3. Veredicto

| Nivel | Significado |
|---|---|
| **A** | Al lab ya, con features existentes o triviales y sin look-ahead |
| **B** | Al lab cuando haya datos de noticias (Alpaca News) |
| **C** | Se mide, con expectativa baja (evidencia débil o negativa tras costes) |
| **D** | No se implementa ahora (contra la evidencia, sin datos o incompatible con los límites) |

| Regla | Familia | Timeframes | Evidencia | Nivel |
|---|---|---|---|---|
| N cierres a la baja seguidos en tendencia alcista | `streak_reversion` | 1h, 4h, 1d | Jegadeesh 1990; Lehmann 1990; Connors y Alvarez 2009 | A |
| RSI(2) muy sobrevendido en tendencia alcista | `rsi2_reversion` | 1h, 4h, 1d | Connors y Alvarez 2009 | A |
| Cierre en la parte baja del rango (IBS bajo) | `ibs_reversion` | 1h, 4h, 1d | Pagonidis 2013 | A |
| Cerca del máximo de 52 semanas | `near_52w_high` | 1d | George y Hwang 2004 | A |
| Cambio de mes | `turn_of_month` | 1d, sólo acciones | Ariel 1987; Lakonishok y Smidt 1988; McConnell y Xu 2008 | A |
| Subida fuerte con noticias anómalas → deriva | `news_drift` | 1h, 1d, acciones | Chan 2003 | B |
| Caída fuerte sin noticias → rebote | `quiet_drop_reversal` | 1h, 1d, acciones | Chan 2003 | B |
| Resultados + gap al alza + volumen → deriva | `earnings_gap_drift` | 1h, 1d, acciones | Bernard y Thomas 1989 | B |
| Envolvente o martillo + sobreventa + tendencia | `candle_reversal` | 1h, 4h, 1d | Marshall, Young y Rose 2006; Horton 2009 | C |
| IPO: sube, cae (compra), se estabiliza (vende) | — | — | Ritter 1991; Field y Hanka 2001 | D |
| Deriva antes de la Fed (pre-FOMC) | — | — | Lucca y Moench 2015 | D |
| Deriva nocturna (comprar al cierre, vender a la apertura) | — | — | Lou, Polk y Skouras 2019 | D |
| Sentimiento puntuado por un LLM como feature de backtest | — | — | Lopez-Lira y Tang 2023; Glasserman y Lin 2023 | D |

## 4. Fichas

### 4.1 `streak_reversion` — «tres bajadas seguidas y rebota» (A)

- **La idea del usuario**, formalizada: se cuenta cuántos cierres seguidos han quedado por debajo
  del cierre anterior (`down_streak`). Una «bajada» es un cierre inferior al anterior (no una vela
  roja), que es como lo mide la literatura; así un gap bajista cuenta como bajada aunque la vela
  cierre por encima de su apertura.
- **Mecanismo:** presión vendedora temporal (liquidez, sobrerreacción) que se corrige en días. La
  reversión a corto plazo está documentada en acciones a una semana y un mes (Jegadeesh 1990;
  Lehmann 1990) y, en índices, Connors y Alvarez (2009) la popularizaron con «varios días a la
  baja por encima de la media de 200».
- **Regla:** `down_streak ≥ n` y `close > SMA200`. Sale cuando RSI(2) > 70, por stop de 2,5 ATR
  o por tiempo. Grid: `n ∈ {2, 3, 4}`, `hold ∈ {3, 6}` barras (6 variantes).
- **Por qué el filtro de tendencia:** sin él, comprar caídas es coger cuchillos que caen; con él,
  se compran retrocesos dentro de una subida.
- **Qué esperar:** es la más conocida del grupo y una de las más explotadas; en acciones grandes
  y ETFs funcionó bien hasta ~2010 y desde entonces de forma irregular.

### 4.2 `rsi2_reversion` (A)

- RSI de 2 periodos (`rsi_2`) < 5, 10 o 15 por encima de la SMA200; sale con RSI(2) > 70.
- Mide lo mismo que la racha pero con intensidad: tres caídas pequeñas no cuentan igual que una
  grande. Evidencia de practicantes, no académica, y con decaimiento tras publicarse.

### 4.3 `ibs_reversion` (A)

- **IBS** (Internal Bar Strength) = posición del cierre en el rango de la vela
  (`close_position`, ya existía). IBS < 0,1–0,2 en tendencia alcista → compra; sale con IBS > 0,7.
- Pagonidis (2013) lo documenta en ETFs de índices: cierres en mínimos del día tienden a rebotar
  al día siguiente. Rotación alta → sensible a costes; en Alpaca el coste es casi sólo spread.

### 4.4 `near_52w_high` (A, sólo 1d)

- `dist_high_252` = cierre / máximo de 252 barras − 1. Entra a menos de un 2–5 % del máximo con
  precio > SMA200; sale si cae un 10 % por debajo del máximo, por stop o por tiempo (20–60 días).
- George y Hwang (2004): el máximo de 52 semanas actúa como ancla; los inversores tardan en
  aceptar precios por encima y la noticia se incorpora despacio. Explica buena parte del momentum.
- Sólo en barras diarias: 252 barras de 1 h no son «52 semanas».

### 4.5 `turn_of_month` (A, sólo 1d y acciones)

- Entra cuando quedan ≤ 2 o ≤ 4 días naturales para fin de mes (`days_to_month_end`) y sale a
  partir del día 3 del mes siguiente (`day_of_month`), o como mucho a las 8 barras.
- Ariel (1987), Lakonishok y Smidt (1988, 90 años de datos) y McConnell y Xu (2008): buena parte
  de la rentabilidad de la bolsa de EE. UU. se concentra entre el último día del mes y el tercero.
  Mecanismo: flujos de nóminas, planes de pensiones y rebalanceos.
- Sin evidencia equivalente en cripto: no se prueba allí (menos hipótesis inútiles = más potencia).
- Aproximación: días naturales, no hábiles (el calendario de festivos de Alpaca está pendiente).

### 4.6 Reglas con noticias (B)

- **Chan (2003)**: tras un movimiento fuerte, las acciones **con** noticias públicas siguen en la
  misma dirección (deriva) y las que se mueven **sin** noticias tienden a revertir. Es una de las
  pocas reglas sobre noticias con base académica, y se puede aplicar sólo con compras: comprar
  subidas con noticias y caídas sin noticias.
- **Bernard y Thomas (1989), PEAD**: tras unos resultados que sorprenden, el precio sigue
  ajustándose durante semanas. Aproximación sin datos de consenso: titular de resultados + gap al
  alza + volumen anómalo.
- **Requisito:** titulares históricos con fecha y hora de publicación, por valor (Alpaca News).
  Las features se calculan sólo con titulares publicados antes del cierre de la vela, con un
  margen para que research y vivo vean lo mismo.
- **Las grandes tecnológicas tienen noticias casi todos los días**, así que «con o sin noticias»
  se mide como intensidad anómala frente a su media, no como presencia.
- **Estado:** pendiente de implementar (fase 2 de este bloque).

### 4.7 `candle_reversal` — patrones de velas (C)

- Envolvente alcista o martillo, RSI < 35–45, precio > EMA200; objetivo 3 ATR, stop 2 ATR.
- **Evidencia mayoritariamente negativa** una vez descontados costes en acciones de EE. UU.
  (Marshall, Young y Rose 2006 sobre el Dow Jones; Horton 2009). Algo de evidencia en mercados
  menos eficientes. Se incluye porque es barata (2 variantes) y porque es exactamente el tipo de
  creencia popular que el sistema debe poder confirmar o tumbar con datos.
- La familia `candlestick` del research manual sigue existiendo; esta es la versión que el lab
  prueba de forma automática.

### 4.8 IPO: «sube, cae, compro, se estabiliza, vendo» (D)

- **Lo documentado va en contra:** la subida del primer día existe, pero sólo la captura quien
  recibe acciones en la colocación. Después, las IPO rinden peor que empresas comparables durante
  tres años (Ritter 1991), y al terminar el periodo de bloqueo (lock-up, ~180 días) el precio cae
  de media un 1–3 % (Field y Hanka 2001), que sólo se aprovecha vendiendo en corto (prohibido aquí).
- **Faltan datos:** se necesitarían cientos de IPO con su historia completa, **incluidas las que
  luego dejaron de cotizar** (si no, sólo vemos las supervivientes y el resultado sale inflado).
  Hoy no hay fuente para eso.
- **El sistema tampoco las vería:** las reglas necesitan ~200 barras de historia para sus medias.
- **Uso útil a futuro:** como filtro («no comprar valores con menos de 6 meses cotizando» o
  «evitar la semana del fin del lock-up»), no como regla de compra.

### 4.9 Descartadas por ahora (D)

- **Pre-FOMC** (Lucca y Moench 2015): fuerte en 1994–2011, mucho más débil desde su publicación;
  requiere el calendario de la Fed. Candidata a una iteración posterior.
- **Deriva nocturna** (Lou, Polk y Skouras 2019): la rentabilidad de los índices se concentra de
  la noche a la mañana, pero explotarla exige órdenes al cierre y a la apertura que el motor aún
  no modela.
- **Sentimiento de noticias puntuado por un LLM como feature de backtest:** el modelo se entrenó
  con texto posterior a muchos de esos titulares y «sabe» qué pasó después (Glasserman y Lin 2023):
  cualquier backtest sería optimista por construcción. Un LLM sólo puede evaluarse hacia delante
  (en sombra, con titulares posteriores a su fecha de corte). Por eso las features de noticias
  del lab son deterministas (conteos y clasificación por palabras clave) y el LLM se usa para
  leer y resumir, no para puntuar.

## 5. Limitación principal y siguiente paso

El lab prueba cada regla **símbolo a símbolo**. Las anomalías diarias disparan pocas veces al año
por valor, así que con 10 acciones muchas variantes caerán por «muestra insuficiente», aunque el
efecto exista en el conjunto. Mitigaciones en este bloque: las reglas de reversión también se
prueban en 1h y 4h (más ocasiones), y las diarias usan 5 años de historia (`daily_days`).

Siguiente paso recomendado: **prueba agrupada (panel)**, es decir, una regla evaluada sobre todos
los símbolos a la vez, que es como se documentaron estos efectos. También hace falta un universo
con valores deslistados para evitar el sesgo de supervivencia (R12.11).

## 6. Referencias

- Ariel, R. (1987). A monthly effect in stock returns. *Journal of Financial Economics*.
- Bernard, V. y Thomas, J. (1989). Post-earnings-announcement drift: delayed price response or
  risk premium? *Journal of Accounting Research*.
- Chan, W. S. (2003). Stock price reaction to news and no-news: drift and reversal after headlines.
  *Journal of Financial Economics*.
- Connors, L. y Alvarez, C. (2009). *Short Term Trading Strategies That Work*.
- Field, L. y Hanka, G. (2001). The expiration of IPO share lockups. *Journal of Finance*.
- George, T. y Hwang, C.-Y. (2004). The 52-week high and momentum investing. *Journal of Finance*.
- Glasserman, P. y Lin, C. (2023). Assessing look-ahead bias in stock return predictions generated
  by GPT sentiment analysis.
- Horton, M. (2009). Stars, crows, and doji: the use of candlesticks in stock selection.
  *Quarterly Review of Economics and Finance*.
- Jegadeesh, N. (1990). Evidence of predictable behavior of security returns. *Journal of Finance*.
- Lakonishok, J. y Smidt, S. (1988). Are seasonal anomalies real? A ninety-year perspective.
  *Review of Financial Studies*.
- Lehmann, B. (1990). Fads, martingales, and market efficiency. *Quarterly Journal of Economics*.
- Lopez-Lira, A. y Tang, Y. (2023). Can ChatGPT forecast stock price movements? Return
  predictability and large language models.
- Lou, D., Polk, C. y Skouras, S. (2019). A tug of war: overnight versus intraday expected returns.
  *Journal of Financial Economics*.
- Lucca, D. y Moench, E. (2015). The pre-FOMC announcement drift. *Journal of Finance*.
- Marshall, B., Young, M. y Rose, L. (2006). Candlestick technical trading strategies: can they
  create value for investors? *Journal of Banking & Finance*.
- McConnell, J. y Xu, W. (2008). Equity returns at the turn of the month. *Financial Analysts
  Journal*.
- McLean, R. D. y Pontiff, J. (2016). Does academic research destroy stock return
  predictability? *Journal of Finance*.
- Pagonidis, A. (2013). The IBS effect: mean reversion in equity ETFs. NAAIM.
- Ritter, J. (1991). The long-run performance of initial public offerings. *Journal of Finance*.
