# Roadmap

Detalle requisito por requisito en [`prd-traceability.md`](prd-traceability.md).

| Paso | Descripción | Estado |
|---|---|---|
| 1 | Repositorio, CI, tests, `.env.example`, exclusión de secretos | ✅ iteración 1 |
| 2 | Proyecto Supabase: esquema, RLS, auditoría de configuración | 🟡 esquema + hardening aplicados en «Autonomous trading» (advisor de seguridad limpio); faltan Vault, Storage y Auth |
| 3 | Research Engine + CLI con informe reproducible | ✅ |
| 4 | Strategy DSL | ✅ |
| 5 | Statistical Validation Engine | ✅ (OOS, WF, purged CV, Bayes, MC, FDR, costes, régimen) |
| 6 | Risk Engine aislado, alta cobertura | ✅ (≥95 % exigido en CI) |
| 7 | Cuenta Demo Trading 212 + credenciales en el gestor de secretos | ⏳ manual (usuario) |
| 8 | `Trading212Broker` real (demo) | ⏳ iteración 2 |
| 9 | Paper Trader: Signal → Risk → Broker, registrar todas las decisiones | 🟡 streaming paper sobre Binance ✅ (bloque 2); contra T212 Demo ⏳ |
| 10 | Shadow Engine (Champion, Challengers, Buy & Hold, Cash) + counterfactuals | 🟡 sombra por estrategia + Buy & Hold + champion/challenger del Research Lab ✅; Cash ⏳ |
| 11 | AI Analyst (OpenAI) con salida estructurada, sin acceso a órdenes | ✅ local: propone hipótesis en el DSL que el Research Lab examina (bloque 4); sincronización con Supabase ⏳ |
| 12 | Autonomous Research Loop (Railway cron) | 🟡 bucle completo en local (research cada 6 h, revisión y meta-learning cada hora); Railway ⏳ |
| 13 | Dashboard | 🟡 dashboard local en localhost ✅; Lovable/Vercel ⏳ |
| 14 | Deploy (Vercel / Supabase / Railway) | ⏳ (de momento todo corre en local) |
| 15 | Seguridad: entornos DEV/PAPER/LIVE, kill switch global | 🟡 flags en código; kill switch operativo en el dashboard local |
| 16 | Go-live gate (100 €) | 🟡 puerta automática con 10 criterios, panel en el dashboard y aviso (bloque 4); falta el adaptador de broker real |

## Bloque 1 (en curso): research con datos reales

- ✅ `YahooAdapter` + comando `fetch` → Parquet; universo invertible en T212 UE.
- ✅ Comando `study`: símbolos × estrategias con FDR global y costes Trading 212.
- ✅ `SupabaseStore` para guardar experimentos y backtests (`study --persist`).
- ⏳ Ejecutar con datos reales: requiere permitir en la red del entorno
  `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `fc.yahoo.com`, `guce.yahoo.com` y
  `nzeuzxtpqrsvyvpxaugz.supabase.co`, y el secreto `SUPABASE_SERVICE_ROLE_KEY`.

## Bloque 2 (en curso): trader en streaming, local

Petición del usuario (2026-10-01): un bot rápido y dinámico que compre y venda muchas veces al
día, ejecutable en local con frontal en localhost. Mercado elegido: **cripto spot en Binance**
(Trading 212 no ofrece precios en streaming ni la frecuencia de órdenes necesaria).

- ✅ Feed en tiempo real (WebSocket bookTicker + aggTrade) con reconexión y grabación de ticks.
- ✅ Motor por eventos idéntico en vivo y en replay: velas de segundos → features incrementales →
  estrategias (momentum de flujo de órdenes, reversión) a horizontes de 1–20 min.
- ✅ Filtro de costes: objetivo ≥ 2× (comisiones + spread + slippage); se cuentan las señales
  bloqueadas para ver si el mercado paga las comisiones.
- ✅ Libro en sombra por estrategia = evidencia forward (Edge Score, BH-FDR); el libro paper sólo
  opera lo que aprueba el Risk Engine con esa evidencia.
- ✅ Exchange paper con latencia, bid/ask real, impacto y comisión 0,10 %.
- ✅ SQLite local + dashboard en localhost (kill switch, pausa, cerrar todo, agresividad).
- ✅ Simulación sobre historia real (velas de 1 s de Binance) con el mismo motor, visual en el
  dashboard o `--headless`, con benchmark Buy & Hold. Primer resultado (72 h, BTC/ETH/SOL, 10.000):
  ninguna de las 5 reglas iniciales tiene EV positivo ni con comisiones ≈ 0 → 0 operaciones
  paper. Las reglas a mano no bastan: hace falta el bucle de research (siguiente punto).
- ✅ **Research Lab** (bloque 3): ver abajo.

## Bloque 3 (en curso): aprendizaje continuo + acciones

- ✅ Universo automático: los 10 pares USDC más líquidos (`top:10`).
- ✅ Un solo lenguaje de reglas (DSL) para investigar y operar; paridad research ↔ motor testeada.
- ✅ Catálogo intradía (7 familias, ~1.800 hipótesis por ciclo con 10 símbolos) sobre el pipeline
  existente (IS → BH-FDR → OOS → walk-forward → Monte Carlo → FDR global), en paralelo.
- ✅ Comprobación *golden*: la regla debe ganar también en el motor real (latencia, bid/ask, fees).
- ✅ Registro champion/challenger con transiciones auditadas y lecciones; carga en caliente.
- ✅ Revisión forward: promoción a champion, degradación y retirada automática.
- ✅ Meta-learning (scikit-learn): aprende de las operaciones ganadoras y perdedoras de cada
  estrategia un filtro validado sin fugas; si mejora fuera de muestra nace una versión challenger.
- ✅ Programación: research cada 6 h en un proceso aparte + revisión/aprendizaje cada hora;
  `simulate --learn` reproduce el bucle sobre la historia sin mirar el futuro.
- ✅ Acciones de EE. UU.: sesión 09:30–16:00 NY (intradía, sin posiciones nocturnas), flujo BVC,
  historia Yahoo (sin clave, ~7 días) o Alpaca (con clave, años), streaming Alpaca IEX.
- Resultado real a 2026-10-01: 0 reglas sobreviven en cripto (1.790 hipótesis, 7 días) ni en
  acciones (historia Yahoo insuficiente); el sistema, correctamente, no opera.
- ⏳ Claves Alpaca del usuario (historia larga de acciones + streaming).
- ⏳ Festivos de mercado desde el calendario de Alpaca.
- ⏳ Órdenes *maker* (límite post-only) para reducir comisiones; modelo de cola.
- ⏳ Benchmarks Buy & Hold / Cash en la sombra; informe de replay en Markdown.
- ⏳ Adaptador Binance real + go-live gate específico (no antes de evidencia forward suficiente).

## Bloque 4 (en curso): buscar ventaja real + Analista IA

Contexto: a horizontes de minutos ninguna regla sobrevive a los costes, y en acciones la mayoría
de pruebas fallaban por muestra insuficiente. Se amplía dónde buscar, sin relajar el rigor.

- ✅ Historia larga a varias escalas: klines de Binance (1h, 4h, 1d) y barras de Alpaca
  remuestreadas (15min, 1h, 1d) con caché; 365 días por defecto.
- ✅ Research multi-timeframe (cripto 1min/1h/4h, acciones 15min/1h) con **un único FDR global**
  sobre todas las hipótesis de todos los timeframes.
- ✅ Features entre valores (rango de retorno en el universo, fuerza relativa, amplitud de
  mercado) y de calendario, retrasadas una barra; paridad research ↔ vivo testeada.
- ✅ Catálogo swing (≥ 1 h): momentum y reversión entre valores, fuerza relativa, tendencia,
  ruptura con volumen, amplitud. Las reglas ≥ 1 h mantienen posiciones entre sesiones (sin
  *day trades*, evita la regla PDT); las intradía siguen cerrando antes del cierre.
- ✅ **Analista IA** (`packages/aqt/analyst`, OpenAI): lee lecciones, checks que fallan, mejores
  pares, evidencia forward y sus propias hipótesis anteriores; propone reglas en el DSL que se
  validan estrictamente y el lab examina en el mismo FDR global. Presupuesto diario, aislado de
  brokers y riesgo (test). Panel «Analista IA» en el dashboard.
- ✅ **Puerta a real**: cada hora evalúa la cuenta paper (≥ 28 días, ≥ 50 operaciones, neto
  positivo, ventaja significativa, ≥ 3 de 4 semanas positivas, mejor que Buy & Hold, caída dentro
  del límite, órdenes por un broker paper externo sin descuadres, kill switch probado). Avisa una
  vez cuando cambia (banner + webhook opcional al móvil). No activa nada por sí misma.
- ⏳ Familias de pares, correlación y beta contra benchmark; sincronizar `hypotheses` con la
  tabla `ai_hypotheses` de Supabase.

## Bloque 5 (en curso): reglas documentadas + noticias del día

Petición del usuario (2026-10-02): ¿estudia el sistema reglas como «tres bajadas seguidas y
rebota» o el patrón de las salidas a bolsa? Respuesta: estudio de reglas con evidencia publicada
([`estudio-reglas.md`](estudio-reglas.md)) y noticias reales como punto de entrada diario.

- ✅ Estudio: qué reglas probar (A), cuáles cuando haya noticias (B), cuáles medir con
  expectativa baja (C) y cuáles no (D, incluido el patrón de IPO), con referencias.
- ✅ Features nuevas sin look-ahead: rachas de cierres (`down_streak`, `up_streak`), `rsi_2`,
  `dist_high_252`, día del mes y días a fin de mes.
- ✅ Familias nuevas en el lab: `streak_reversion`, `rsi2_reversion`, `ibs_reversion`,
  `candle_reversal` (1h/4h/1d), `near_52w_high` (1d) y `turn_of_month` (1d, acciones).
- ✅ Barras diarias en el lab con 5 años de historia (cripto y acciones).
- ⏳ Noticias reales (Alpaca News) como features deterministas y familias de Chan (2003) y PEAD.
- ⏳ «Noticias del día»: el Analista IA resume los titulares reales del día (con la fecha) y
  propone hipótesis; nunca opera.
- ⏳ Prueba agrupada (panel) entre símbolos para las reglas diarias.

## Próximos pasos técnicos sugeridos

- Persistir resultados del pipeline en Supabase (`experiments`, `backtests`, `walk_forward_runs`).
- Descarga de datos reales a Parquet (p. ej. proveedor gratuito vía `MarketDataAdapter`).
- Barrido multi-símbolo con FDR global sobre todo el universo de hipótesis.
- Probabilistic / Deflated Sharpe Ratio.
- Aceleración (numba / vectorbt) para barridos de decenas de miles de variantes.
