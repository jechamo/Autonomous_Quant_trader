# Estudio de reglas: qué merece la pena aplicar

**Fecha:** 2026-10-02 (revisado el mismo día: auditoría de fuentes, § 6) · **Implementación:** `packages/aqt/strategies/swing.py` (familias),
`packages/aqt/features/engine.py` y `packages/aqt/features/cross_section.py` (features),
`packages/aqt/news/` (noticias). **Trazabilidad:** R10.27–R10.36, R11.28–R11.32, R12.30–R12.31,
R21.23–R21.24.

## 1. Cómo leer este estudio

Este documento no dice «esta regla funciona». Dice **qué reglas merece la pena someter al Research
Lab** y por qué. Cada regla entra como hipótesis y pasa por el mismo camino que todas:

```
in-sample (barrido de parámetros) → FDR → out-of-sample congelado → walk-forward → Monte Carlo
→ FDR global (todas las hipótesis, símbolos y timeframes) → golden check en el motor real
→ challenger en sombra (evidencia forward desde cero) → Risk Engine
```

Si no sobrevive, no opera. Que una regla aparezca aquí sólo significa que merece gastar en ella
parte del presupuesto de hipótesis (cada variante nueva hace más estricto el FDR para todas las
demás). Cada ficha dice **qué respalda exactamente la fuente citada y qué es extrapolación
nuestra**; la § 6 hace lo mismo con todas las familias del sistema, también las anteriores.

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
| **A** | Efecto publicado y replicado, aplicado como en el estudio (mismo tipo de activo y horizonte) |
| **B** | Efecto publicado, pero lo aplicamos fuera de las condiciones del estudio (otro horizonte, otro activo, sólo la pata larga) |
| **C** | Sin respaldo académico (heurística de practicantes) o con evidencia negativa tras costes: se mide con expectativa baja |
| **D** | No se implementa ahora (contra la evidencia, sin datos o incompatible con los límites) |

| Regla | Familia | Timeframes | Evidencia | Nivel |
|---|---|---|---|---|
| N cierres a la baja seguidos en tendencia alcista | `streak_reversion` | 1h, 4h, 1d | Ninguna académica; heurística de Connors y Alvarez 2009 | C |
| RSI(2) muy sobrevendido en tendencia alcista | `rsi2_reversion` | 1h, 4h, 1d | Ninguna académica; Connors y Alvarez 2009 | C |
| Cierre en la parte baja del rango (IBS bajo) | `ibs_reversion` | 1d | Pagonidis 2014 (ETFs de índices) | A en SPY/QQQ, B en acciones |
| Cerca del máximo de 52 semanas | `near_52w_high` | 1d | George y Hwang 2004 (larga-corta, 6–12 meses) | B |
| Cambio de mes | `turn_of_month` | 1d, sólo acciones | Ariel 1987; Lakonishok y Smidt 1988; McConnell y Xu 2008 | A |
| Subida fuerte con noticias anómalas → deriva | `news_drift` | 1h, 4h, 1d, acciones | Chan 2003 (mensual; deriva sobre todo tras malas noticias) | C |
| Caída fuerte sin noticias → rebote | `quiet_drop_reversal` | 1h, 4h, 1d, acciones | Chan 2003 (horizonte mensual) | B |
| Resultados + gap al alza + volumen → deriva | `earnings_gap_drift` | 1h, 4h, 1d, acciones | Bernard y Thomas 1989; Brandt et al. 2008 | B |
| Envolvente o martillo + sobreventa + tendencia | `candle_reversal` | 1h, 4h, 1d | Marshall, Young y Rose 2006; Horton 2009 | C |
| IPO: sube, cae (compra), se estabiliza (vende) | — | — | Ritter 1991; Field y Hanka 2001 | D |
| Deriva antes de la Fed (pre-FOMC) | — | — | Lucca y Moench 2015 | D |
| Momentum nocturno (comprar al cierre, vender a la apertura) | — | — | Lou, Polk y Skouras 2019 | D |
| Sentimiento puntuado por un LLM como feature de backtest | — | — | Lopez-Lira y Tang 2023; Glasserman y Lin 2023 | D |

## 4. Fichas

### 4.1 `streak_reversion` — «tres bajadas seguidas y rebota» (C)

- **Origen:** un ejemplo inventado por el usuario. **No es una regla demostrada.** No hay ningún
  estudio académico que mida «N cierres seguidos a la baja → rebote».
- **Lo que sí existe y se le parece:** la reversión a corto plazo **entre valores** (Jegadeesh
  1990; Lehmann 1990): los valores que más cayeron la última semana o mes, comparados con el
  resto, tienden a recuperar algo después. Es un efecto de ranking entre muchas acciones, no una
  secuencia de velas en una sola; ese efecto ya lo prueba la familia `xs_reversal`.
- **Versión de practicantes:** Connors y Alvarez (2009), un libro de trading con backtests
  propios (sin revisión académica), proponen comprar índices tras varios días a la baja por
  encima de la media de 200. La rentabilidad de estas reglas cayó tras popularizarse.
- **Regla:** se cuentan los cierres seguidos por debajo del cierre anterior (`down_streak`, no
  velas rojas). Entrada con `down_streak ≥ n` y `close > SMA200`; salida con RSI(2) > 70, stop de
  2,5 ATR o por tiempo. Grid `n ∈ {2, 3, 4}`, `hold ∈ {3, 6}` (6 variantes).
- **Por qué se prueba igualmente:** es barata (6 variantes), tiene un mecanismo plausible
  (presión vendedora temporal) y es justo el tipo de creencia que el sistema debe poder tumbar
  o confirmar con datos. Expectativa baja.

### 4.2 `rsi2_reversion` (C)

- RSI de 2 periodos (`rsi_2`) < 5, 10 o 15 por encima de la SMA200; sale con RSI(2) > 70.
- **Fuente:** sólo Connors y Alvarez (2009). Sin validación académica; mide lo mismo que la racha
  pero con intensidad. Expectativa baja.

### 4.3 `ibs_reversion` (A en ETFs de índices, B en acciones)

- **IBS** (Internal Bar Strength) = posición del cierre en el rango de la vela
  (`close_position`). IBS < 0,1–0,2 en tendencia alcista → compra; sale con IBS > 0,7.
- **Fuente:** Pagonidis (2014, premio NAAIM, no revista académica) en **ETFs de índices con
  velas diarias**: con IBS < 0,2 el día siguiente subió de media un 0,35 %; efecto estable desde
  los 90 y más fuerte con volatilidad alta.
- **Aplicación:** sólo velas diarias. En SPY y QQQ es la condición del estudio (A); en acciones
  sueltas es extrapolación (B). Rotación alta: sensible a costes (en Alpaca, casi sólo spread).

### 4.4 `near_52w_high` (B, sólo 1d)

- `dist_high_252` = cierre / máximo de 252 barras − 1. Entra a menos de un 2–5 % del máximo con
  precio > SMA200; sale si cae un 10 % por debajo del máximo, por stop o por tiempo (60 o 126
  sesiones, es decir 3 o 6 meses).
- **Fuente:** George y Hwang (2004): ordenan acciones por cercanía al máximo de 52 semanas,
  compran el 30 % más cercano, venden en corto el 30 % más lejano y mantienen 6 o 12 meses. El
  máximo actúa como ancla y la información se incorpora despacio; explica buena parte del
  momentum y no revierte a largo plazo.
- **Diferencias con el estudio (por eso B):** usamos sólo la pata larga (no se permiten cortos),
  un umbral fijo en vez de un ranking y 10 acciones en lugar de todo el mercado.
- Sólo en barras diarias: 252 barras de 1 h no son «52 semanas».

### 4.5 `turn_of_month` (A, sólo 1d y acciones)

- Entra cuando quedan ≤ 2 o ≤ 4 días naturales para fin de mes (`days_to_month_end`) y sale a
  partir del día 3 del mes siguiente (`day_of_month`), o como mucho a las 8 barras.
- **Fuentes:** Lakonishok y Smidt (1988), Dow Jones 1897–1986: los cuatro días del último día
  hábil del mes al tercero del siguiente sumaron de media un 0,47 %, más que el mes entero
  (0,35 %). Ariel (1987) y McConnell y Xu (2008) lo confirman en otras muestras. Mecanismo
  propuesto: flujos de nóminas, planes de pensiones y rebalanceos.
- **Evidencia reciente mixta:** estudios posteriores a su publicación lo encuentran más débil en
  algunos periodos; es el caso típico de McLean y Pontiff.
- Sin evidencia equivalente en cripto: no se prueba allí (menos hipótesis inútiles = más potencia).
- Aproximación: días naturales, no hábiles (el calendario de festivos de Alpaca está pendiente).

### 4.6 Reglas con noticias (B y C)

- **Chan (2003)**, con rentabilidades **mensuales**: los movimientos extremos **sin** noticias
  públicas tienden a revertir, y los que vienen **con** noticias siguen en la misma dirección,
  sobre todo tras **malas** noticias. Para un sistema que sólo compra, lo aprovechable es comprar
  caídas extremas sin noticias (`quiet_drop_reversal`, B porque lo aplicamos a días y horas, no
  a meses). Comprar subidas con noticias (`news_drift`) se apoya en la parte más débil del
  estudio: nivel C.
- **Bernard y Thomas (1989), PEAD**: tras unos resultados que sorprenden, el precio sigue
  ajustándose: ~2 % en 60 sesiones para las sorpresas más positivas, más en empresas pequeñas.
  Sin datos de consenso de analistas usamos la reacción del precio como medida de sorpresa, como
  Brandt et al. (2008): titular de resultados + gap al alza + volumen anómalo. En las grandes
  tecnológicas del universo el efecto esperado es pequeño.
- **Requisito:** titulares históricos con fecha y hora de publicación, por valor (Alpaca News).
  Las features se calculan sólo con titulares publicados antes del cierre de la vela, con un
  margen para que research y vivo vean lo mismo.
- **Las grandes tecnológicas tienen noticias casi todos los días**, así que «con o sin noticias»
  se mide como intensidad anómala frente a su media, no como presencia.
- **Implementación:** `news_1d` (titulares de las últimas 24 h), `news_ratio` (intensidad frente a
  la media de los 20 días previos) y `news_earnings_1d` (titulares de resultados según un
  clasificador de palabras clave). Sólo cuentan titulares publicados al menos 5 minutos antes del
  cierre de la vela; sin cobertura de noticias el valor es NaN, nunca «sin noticias». Se prueban
  sólo en acciones y sólo si hay claves de Alpaca (3 años de titulares por defecto).
- **Reglas:** `news_drift` (`news_ratio > 2–3`, subida > 2 %, volumen > 1,5×),
  `quiet_drop_reversal` (caída > 2–4 % con `news_ratio < 1`, sobre SMA200) y
  `earnings_gap_drift` (titular de resultados, gap > 2–5 %, volumen > 2×).

### 4.7 `candle_reversal` — patrones de velas (C)

- Envolvente alcista o martillo, RSI < 35–45, precio > EMA200; objetivo 3 ATR, stop 2 ATR.
- **Evidencia negativa en EE. UU.:** Marshall, Young y Rose (2006), acciones del Dow Jones
  1992–2001, no encuentran rentabilidad superior a operar al azar; Horton (2009), 349 acciones
  del S&P 500, tampoco. Hay algún resultado positivo en mercados menos eficientes (Taiwán,
  Tailandia). Se incluye porque es barata (2 variantes) y porque es exactamente el tipo de
  creencia popular que el sistema debe poder confirmar o tumbar con datos.
- La familia `candlestick` del research manual sigue existiendo; esta es la versión que el lab
  prueba de forma automática.

### 4.8 IPO: «sube, cae, compro, se estabiliza, vendo» (D)

- **Lo documentado va en contra:** la subida del primer día existe, pero sólo la captura quien
  recibe acciones en la colocación. Después, las IPO rinden peor que empresas comparables durante
  tres años (Ritter 1991), y al terminar el periodo de bloqueo (lock-up, normalmente 180 días) el
  precio cae de media un 1,5 % en tres días (Field y Hanka 2001, 1.948 lock-ups; más en empresas
  con capital riesgo), que sólo se aprovecha vendiendo en corto (prohibido aquí).
- **Faltan datos:** se necesitarían cientos de IPO con su historia completa, **incluidas las que
  luego dejaron de cotizar** (si no, sólo vemos las supervivientes y el resultado sale inflado).
  Hoy no hay fuente para eso.
- **El sistema tampoco las vería:** las reglas necesitan ~200 barras de historia para sus medias.
- **Uso útil a futuro:** como filtro («no comprar valores con menos de 6 meses cotizando» o
  «evitar la semana del fin del lock-up»), no como regla de compra.

### 4.9 Descartadas por ahora (D)

- **Pre-FOMC** (Lucca y Moench 2015): +0,49 % de media en las 24 h previas a las reuniones de la
  Fed entre 1994 y 2011; tras publicarse (2011) prácticamente desapareció. No compensa.
- **Momentum nocturno** (Lou, Polk y Skouras 2019): los beneficios de las estrategias de momentum
  llegan entre el cierre y la apertura, y los del resto de estrategias durante la sesión.
  Explotarlo exige órdenes al cierre y a la apertura que el motor aún no modela.
- **Sentimiento de noticias puntuado por un LLM como feature de backtest:** Lopez-Lira y Tang
  (2023) encuentran que la puntuación de GPT predice la rentabilidad del día siguiente, sobre todo
  en empresas pequeñas y con malas noticias, y que el efecto baja según se extiende su uso. El
  problema es probarlo con historia: un modelo puede haber leído lo que pasó después de cada
  titular. Glasserman y Lin (2023) lo midieron y, dentro del periodo de entrenamiento, pesó más
  otro sesgo («distracción» por lo que el modelo sabe de la empresa) que el look-ahead; fuera de
  él el look-ahead no aplica. Como no se puede descartar, aquí el LLM no puntúa noticias para
  backtests: las features del lab son deterministas (conteos y palabras clave) y el LLM sólo lee
  y resume. Una puntuación por LLM sólo podría evaluarse hacia delante, en sombra.

## 5. Muestra: prueba agrupada en barras diarias

Probadas símbolo a símbolo, las reglas diarias disparan pocas veces al año por valor y casi
todas caerían por «muestra insuficiente» aunque el efecto exista. Por eso, en barras diarias, el
lab las prueba **agrupadas** sobre todo el universo, que es como se documentaron
(`packages/aqt/research/panel.py`):

- Una sola frontera entre entrenamiento y prueba, **la misma fecha para todos los valores**, y lo
  mismo en el walk-forward: nada posterior a esa fecha informa la selección.
- **La unidad de evidencia es la fecha, no la operación**: si ocho valores compran el mismo día
  porque cae todo el mercado, cuenta como una observación (la media de ese día). Diez copias de
  la misma acción no dan más significación que una, y un efecto simultáneo en todos los valores
  (como el cambio de mes) no gana muestra al agruparse: es lo correcto.
- La regla superviviente se registra una vez («todos los valores»), ocupa un solo hueco de reglas
  vivas y acumula su evidencia forward con las operaciones de todos.

En 1h y 4h se sigue probando símbolo a símbolo. Pendiente: un universo con valores deslistados
para evitar el sesgo de supervivencia (R12.11).

## 6. Auditoría de todas las familias del sistema

Revisión hecha el 2026-10-02 contra las fuentes originales. **Respaldo**: «estudio» = la regla
reproduce un efecto publicado en sus condiciones; «extrapolación» = efecto publicado aplicado a
otro horizonte, activo o sólo con compras; «ninguno» = regla hecha a mano o de practicantes.
Que una familia tenga respaldo «ninguno» no la excluye: el lab la examina igual. Sólo significa
que nadie debe creer que funciona antes de que lo demuestren los datos.

| Familia | Catálogo | Respaldo | Fuente y diferencia con nuestra versión |
|---|---|---|---|
| `xs_momentum`, `xs_momentum_long` | swing | extrapolación | Jegadeesh y Titman (1993): ganadores de 3–12 meses siguen ganando. Nosotros: 20 y 60 barras (en 1h son días) y sólo compras |
| `xs_reversal` | swing | estudio en 1d (5 barras ≈ 1 semana); extrapolación en 1h/4h | Jegadeesh (1990), Lehmann (1990): reversión entre valores a 1 semana–1 mes |
| `relative_strength` | swing | ninguno | Combinación propia de fuerza relativa y amplitud de mercado |
| `trend_follow` | swing | extrapolación | Moskowitz, Ooi y Pedersen (2012): momentum de serie temporal a 12 meses en futuros; las reglas de medias móviles de Brock, Lakonishok y LeBaron (1992) no superan la corrección por *data snooping* fuera de muestra (Sullivan, Timmermann y White 1999) |
| `breakout_volume` | swing | extrapolación (parcial) | Gervais, Kaniel y Mingelgrin (2001): volumen inusual de un día o semana anticipa subidas el mes siguiente; la ruptura de máximos de 20 barras no tiene respaldo propio |
| `breadth_dip` | swing | ninguno | Regla propia |
| `streak_reversion`, `rsi2_reversion` | swing | ninguno | Connors y Alvarez (2009), practicantes (§ 4.1–4.2) |
| `ibs_reversion` | swing (1d) | estudio en ETFs; extrapolación en acciones | Pagonidis (2014) |
| `candle_reversal` | swing | evidencia negativa | Marshall, Young y Rose (2006); Horton (2009) |
| `near_52w_high` | swing (1d) | extrapolación | George y Hwang (2004): larga-corta, 6–12 meses |
| `turn_of_month` | swing (1d, acciones) | estudio | Lakonishok y Smidt (1988); Ariel (1987); McConnell y Xu (2008) |
| `quiet_drop_reversal` | swing (noticias) | extrapolación | Chan (2003), horizonte mensual |
| `news_drift` | swing (noticias) | extrapolación débil | Chan (2003): la deriva fuerte es tras malas noticias |
| `earnings_gap_drift` | swing (noticias) | extrapolación | Bernard y Thomas (1989); Brandt et al. (2008) |
| `flow_breakout`, `flow_momentum`, `rsi_flow_reversion`, `bollinger_reversion`, `vwap_reversion`, `squeeze_breakout`, `trend_pullback` | intradía (minutos) | ninguno a ese horizonte | Reglas de manual de análisis técnico y de flujo de órdenes. Los estudios de desequilibrio de órdenes (p. ej. Chordia y Subrahmanyam 2004) son a horizonte diario, no de minutos tras costes. El sistema ya comprobó en 2026-10 que ninguna sobrevive a las comisiones |
| `momentum`, `mean_reversion`, `breakout`, `trend_following`, `candlestick` | research manual (diario) | ninguno / extrapolación | Ejemplos del DSL; el de velas tiene la evidencia negativa de § 4.7 |
| Momentum en cripto (`trend_follow`, `xs_momentum` sobre Binance) | swing | extrapolación | Liu y Tsyvinski (2021): fuerte momentum de serie temporal semanal en bitcoin, ether y XRP |
| Hipótesis del Analista IA (`ai_*`) | — | ninguno | Ideas generadas por un LLM: se tratan exactamente igual que cualquier otra hipótesis |

### Erratas corregidas en esta revisión

- «Tres bajadas» y RSI(2) estaban como nivel A citando a Jegadeesh y Lehmann, que estudian otra
  cosa (reversión entre valores): ahora son C.
- Pagonidis es de 2014, no de 2013, y su estudio es sólo diario y en ETFs (la familia ya no se
  prueba en 1h/4h).
- `near_52w_high` mantenía 20–60 sesiones; el estudio, 6–12 meses (ahora 60 o 126).
- `news_drift` bajó a C: la deriva tras noticias de Chan es sobre todo tras malas noticias.
- Caída tras el fin del lock-up: −1,5 % en tres días, no «1–3 %».
- Lou, Polk y Skouras hablan del momentum nocturno, no de que los índices suban de noche.
- Glasserman y Lin: se corrigió lo que concluyen sobre el look-ahead de los LLM.

## 7. Referencias

- Ariel, R. (1987). A monthly effect in stock returns. *Journal of Financial Economics*.
- Brandt, M., Kishore, R., Santa-Clara, P. y Venkatachalam, M. (2008). Earnings announcements
  are full of surprises. Working paper.
- Brock, W., Lakonishok, J. y LeBaron, B. (1992). Simple technical trading rules and the
  stochastic properties of stock returns. *Journal of Finance*.
- Bernard, V. y Thomas, J. (1989). Post-earnings-announcement drift: delayed price response or
  risk premium? *Journal of Accounting Research*.
- Chan, W. S. (2003). Stock price reaction to news and no-news: drift and reversal after headlines.
  *Journal of Financial Economics*.
- Connors, L. y Alvarez, C. (2009). *Short Term Trading Strategies That Work*.
- Chordia, T. y Subrahmanyam, A. (2004). Order imbalance and individual stock returns.
  *Journal of Financial Economics*.
- Field, L. y Hanka, G. (2001). The expiration of IPO share lockups. *Journal of Finance*.
- George, T. y Hwang, C.-Y. (2004). The 52-week high and momentum investing. *Journal of Finance*.
- Gervais, S., Kaniel, R. y Mingelgrin, D. (2001). The high-volume return premium. *Journal of
  Finance*.
- Glasserman, P. y Lin, C. (2023). Assessing look-ahead bias in stock return predictions generated
  by GPT sentiment analysis. *Journal of Financial Data Science* (2024).
- Horton, M. (2009). Stars, crows, and doji: the use of candlesticks in stock selection.
  *Quarterly Review of Economics and Finance*.
- Jegadeesh, N. (1990). Evidence of predictable behavior of security returns. *Journal of Finance*.
- Jegadeesh, N. y Titman, S. (1993). Returns to buying winners and selling losers. *Journal of
  Finance*.
- Lakonishok, J. y Smidt, S. (1988). Are seasonal anomalies real? A ninety-year perspective.
  *Review of Financial Studies*.
- Lehmann, B. (1990). Fads, martingales, and market efficiency. *Quarterly Journal of Economics*.
- Liu, Y. y Tsyvinski, A. (2021). Risks and returns of cryptocurrency. *Review of Financial
  Studies*.
- Lopez-Lira, A. y Tang, Y. (2023). Can ChatGPT forecast stock price movements? Return
  predictability and large language models.
- Lou, D., Polk, C. y Skouras, S. (2019). A tug of war: overnight versus intraday expected returns.
  *Journal of Financial Economics*.
- Lucca, D. y Moench, E. (2015). The pre-FOMC announcement drift. *Journal of Finance*.
- Marshall, B., Young, M. y Rose, L. (2006). Candlestick technical trading strategies: can they
  create value for investors? *Journal of Banking & Finance*.
- McConnell, J. y Xu, W. (2008). Equity returns at the turn of the month. *Financial Analysts
  Journal*.
- Moskowitz, T., Ooi, Y. H. y Pedersen, L. H. (2012). Time series momentum. *Journal of
  Financial Economics*.
- McLean, R. D. y Pontiff, J. (2016). Does academic research destroy stock return
  predictability? *Journal of Finance*.
- Pagonidis, A. (2014). The IBS effect: mean reversion in equity ETFs. NAAIM (Founders Award).
- Ritter, J. (1991). The long-run performance of initial public offerings. *Journal of Finance*.
- Sullivan, R., Timmermann, A. y White, H. (1999). Data-snooping, technical trading rule
  performance, and the bootstrap. *Journal of Finance*.
