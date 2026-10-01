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
| 11 | AI Analyst (OpenAI) con salida estructurada, sin acceso a órdenes | ⏳ iteración 3 |
| 12 | Autonomous Research Loop (Railway cron) | 🟡 bucle completo en local (research cada 6 h, revisión y meta-learning cada hora); Railway ⏳ |
| 13 | Dashboard | 🟡 dashboard local en localhost ✅; Lovable/Vercel ⏳ |
| 14 | Deploy (Vercel / Supabase / Railway) | ⏳ (de momento todo corre en local) |
| 15 | Seguridad: entornos DEV/PAPER/LIVE, kill switch global | 🟡 flags en código; kill switch operativo en el dashboard local |
| 16 | Go-live gate (100 €) | ⏳ |

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
- ⏳ Festivos de mercado desde el calendario de Alpaca; órdenes *maker*; AI Analyst (LLM) sólo
  para proponer hipótesis al lab.
- ⏳ Órdenes *maker* (límite post-only) para reducir comisiones; modelo de cola.
- ⏳ Benchmarks Buy & Hold / Cash en la sombra; informe de replay en Markdown.
- ⏳ Adaptador Binance real + go-live gate específico (no antes de evidencia forward suficiente).

## Próximos pasos técnicos sugeridos

- Persistir resultados del pipeline en Supabase (`experiments`, `backtests`, `walk_forward_runs`).
- Descarga de datos reales a Parquet (p. ej. proveedor gratuito vía `MarketDataAdapter`).
- Barrido multi-símbolo con FDR global sobre todo el universo de hipótesis.
- Probabilistic / Deflated Sharpe Ratio.
- Aceleración (numba / vectorbt) para barridos de decenas de miles de variantes.
