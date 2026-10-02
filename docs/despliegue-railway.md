# Llevar el sistema online con Railway (guía para retomarlo)

**Estado:** aparcado a petición del usuario (2026-10-02). Nada de esto está implementado ni
desplegado; hoy todo corre en local. Este documento recoge qué haría falta para tenerlo 24/7 en
la nube. **Trazabilidad:** R21.04 (worker en Railway) y R30.14 (paso 14 «Deploy»), ambos ⏳.

Antes de seguir los pasos, comprueba en la documentación de Railway (docs.railway.com) los
nombres de menús y precios: cambian con frecuencia.

## 1. Qué cambia y qué no

| | En local (hoy) | Online |
|---|---|---|
| Código | El mismo | El mismo, empaquetado en una imagen Docker |
| Modo | PAPER | PAPER: el despliegue no habilita LIVE (sigue exigiendo `TRADING_MODE=LIVE` y `LIVE_TRADING_ENABLED=true`) |
| Risk Engine, límites | Iguales | Iguales |
| Datos y memoria del lab | `data/` en tu disco (SQLite + cachés) | Un **volumen persistente** montado en `data/` |
| Claves | `.env` en tu PC | Variables del servicio en Railway (nunca en el repo) |
| Dashboard | `http://127.0.0.1:8000`, sólo tu PC | Necesita **login** antes de exponerlo (ver § 3) |
| Funciona si apagas el PC | No | Sí |

## 2. Pasos en Railway

1. **Cuenta y proyecto.** Crear cuenta en Railway (plan de pago: el bot corre 24/7) y un
   proyecto nuevo «Deploy from GitHub repo» con este repositorio y la rama principal.
2. **Imagen.** Railway detecta un `Dockerfile` en la raíz. Propuesta (por crear):

   ```dockerfile
   FROM python:3.11-slim
   COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
   WORKDIR /app
   COPY pyproject.toml uv.lock ./
   RUN uv sync --frozen --no-dev
   COPY . .
   # El research usa varios procesos: Railway asigna CPU según el plan.
   CMD ["uv", "run", "python", "-m", "services.trader", "run", "--market", "stocks", \
        "--broker", "alpaca", "--no-open", "--host", "0.0.0.0", "--port", "8000"]
   ```

   Hoy `--host 0.0.0.0` está **prohibido a propósito** en `services/trader/cli.py::run` (el
   dashboard controla el kill switch). Ver § 3 antes de cambiarlo.
3. **Volumen.** Añadir un volumen al servicio montado en `/app/data`. Ahí viven el registro de
   reglas, las operaciones paper, las lecciones, «Noticias del día» (`data/stream/*.sqlite`) y las
   cachés de velas y titulares (varios GB con años de historia: dimensiona el volumen).
   Sin volumen, cada redespliegue empezaría de cero.
4. **Variables.** En la pestaña de variables del servicio (no en el repo):
   `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` (claves **paper**), `OPENAI_API_KEY`,
   `OPENAI_MODEL_STRONG` u `OPENAI_MODEL_CHEAP`, `NOTIFY_WEBHOOK_URL` (avisos al móvil, p. ej.
   ntfy), `TRADING_MODE=PAPER`. Nunca `LIVE_TRADING_ENABLED`.
5. **Reinicio.** Política de reinicio «siempre» / «on failure»: si el proceso cae, Railway lo
   levanta y el bot recupera su estado del volumen (cuenta paper, reglas, controles).
6. **Primer arranque.** La primera ronda de research descarga años de velas de 1 minuto y 3 años
   de titulares por acción: puede tardar bastante (límite de Alpaca de 200 peticiones/min). Las
   siguientes usan la caché del volumen.
7. **Red.** El bot sólo necesita salida a `data.alpaca.markets`, `paper-api.alpaca.markets`,
   `stream.data.alpaca.markets`, `api.openai.com` y (cripto) los dominios de Binance.

## 3. Lo que hay que construir antes: acceso seguro al dashboard

El dashboard permite activar el kill switch, pausar, cerrar posiciones y cambiar la agresividad.
Exponerlo a internet sin autenticación sería entregar el control del bot a cualquiera. Opciones,
de menos a más trabajo:

1. **Sin dashboard público:** el bot corre en Railway sin dominio público; se consulta por los
   avisos al móvil y, si hace falta, con los logs de Railway. Cero riesgo, poca visibilidad.
2. **Login delante del dashboard actual:** un proxy con autenticación (Cloudflare Access,
   Tailscale, o un token largo obligatorio en todas las rutas y en el WebSocket). Cambio de
   código pequeño: permitir `--host 0.0.0.0` **sólo** si hay autenticación configurada, con test.
3. **La versión del PRD:** el bot sincroniza su estado con Supabase (las tablas ya existen en
   `supabase/migrations`) y un dashboard en Vercel con login de Supabase lee de ahí; el kill
   switch y la agresividad se escriben en Supabase y el bot los lee. Es lo más completo y lo que
   más trabajo lleva.

## 4. CPU y coste

- El trading en vivo apenas consume. El **research** (cada 6 h, miles de backtests en paralelo)
  sí: con poca CPU el ciclo tarda más, pero no afecta al trading (va en otro proceso).
- Coste orientativo: plan de pago de Railway con consumo por CPU, memoria y volumen; para un bot
  y su research, del orden de decenas de dólares al mes según la CPU. Alpaca paper es gratis y
  OpenAI cuesta céntimos al día (máximo 6 llamadas).
- Alternativa más barata en CPU: un VPS pequeño (2–4 vCPU) con Docker y la misma imagen; a
  cambio hay que mantener el servidor.

## 5. Comprobaciones tras desplegar

- [ ] Los logs muestran `PAPER trader (stocks, orders -> Alpaca PAPER account)` y el feed conectado.
- [ ] Tras un reinicio manual, la cuenta paper, las reglas y los controles siguen ahí (volumen).
- [ ] Llega el aviso de prueba al móvil (`NOTIFY_WEBHOOK_URL`).
- [ ] El dashboard (si se expone) pide login, y sin él no responde ni `/api/control` ni `/ws`.
- [ ] El ciclo de research termina y «Noticias del día» aparece un día de mercado tras las 08:45
      de Nueva York.
- [ ] El kill switch funciona desde fuera y queda auditado.
- [ ] Ninguna clave aparece en el repo ni en los logs.
