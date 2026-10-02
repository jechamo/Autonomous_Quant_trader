"""What the launcher offers: each way to start the system, what it is for and its options.

Pure data + command building (no UI), so it can be tested against the real CLI. Every command
is PAPER or research: the launcher never offers LIVE trading.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["text", "int", "float", "bool", "choice"]
Value = str | int | float | bool


@dataclass(frozen=True)
class Field:
    key: str
    flag: str  # e.g. "--cash"; for booleans the "on" form ("--learn")
    label: str
    help: str
    kind: Kind
    default: Value
    choices: tuple[tuple[str, str], ...] = ()  # (value, label) for kind="choice"
    off_flag: str = ""  # boolean "off" form ("--no-learn")
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class Mode:
    key: str
    icon: str
    title: str
    summary: str
    when: str
    fixed: tuple[str, ...]  # command and arguments that do not change
    fields: tuple[Field, ...]
    needs: tuple[str, ...] = ()  # "alpaca" | "openai"
    url_port_field: str = ""  # field holding the dashboard port, if any
    notes: tuple[str, ...] = field(default=())


MARKET = Field(
    "market", "--market", "Mercado",
    "Cripto en Binance (24/7) o acciones de EE. UU. (sesión 15:30–22:00 hora de España).",
    "choice", "binance", (("binance", "Cripto · Binance"), ("stocks", "Acciones · EE. UU.")),
)  # fmt: skip
CASH = Field(
    "cash", "--cash", "Capital (USD)",
    "Dinero que el bot puede usar. Pon lo que usarías en real: los tamaños de orden y los "
    "límites de riesgo salen de aquí.",
    "float", 1000.0, minimum=10,
)  # fmt: skip
AGGR = Field(
    "aggressiveness", "--aggressiveness", "Agresividad (0–100)",
    "Cuánto riesgo por operación y cuánta evidencia exige. Nunca supera los límites absolutos "
    "(sin margen, sin cortos, ≤ 2 % por operación). Se puede cambiar luego en el dashboard.",
    "float", 50.0, minimum=0, maximum=100,
)  # fmt: skip
EVERY = Field(
    "research_every", "--research-every", "Research cada (horas)",
    "Cada cuántas horas busca reglas nuevas (y consulta al analista IA). 0 = apagado.",
    "float", 6.0, minimum=0,
)  # fmt: skip
OPEN = Field(
    "open", "--open", "Abrir el navegador",
    "Abre el dashboard automáticamente al arrancar.", "bool", True, off_flag="--no-open",
)  # fmt: skip


def port(default: int) -> Field:
    return Field(
        "port", "--port", "Puerto del dashboard",
        f"El dashboard se abre en http://127.0.0.1:{default}. Usa puertos distintos para tener "
        "varios bots a la vez.",
        "int", default, minimum=1024, maximum=65535,
    )  # fmt: skip


MODES: tuple[Mode, ...] = (
    Mode(
        "crypto_live",
        "₿",
        "Cripto en vivo · paper",
        "El bot opera cripto en tiempo real con dinero ficticio: precios reales de Binance, "
        "compras y ventas simuladas en local, Research Lab cada pocas horas.",
        "Para dejarlo funcionando y ver cómo aprende y opera sin arriesgar nada.",
        ("run", "--market", "binance"),
        (
            Field(
                "symbols",
                "--symbols",
                "Monedas",
                "top:10 = los 10 pares en USDC con más volumen. O una lista: BTCUSDC,ETHUSDC.",
                "text",
                "top:10",
            ),
            CASH,
            AGGR,
            EVERY,
            port(8000),
            OPEN,
        ),
        url_port_field="port",
    ),
    Mode(
        "stocks_alpaca",
        "📈",
        "Acciones · Alpaca paper",
        "Opera acciones de EE. UU. enviando órdenes de verdad a tu cuenta PAPER de Alpaca "
        "(dinero ficticio). Es el modo que cuenta para la puerta a real.",
        "Para la prueba seria antes de plantearte dinero real: unas 4 semanas como mínimo.",
        ("run", "--market", "stocks", "--broker", "alpaca"),
        (CASH, AGGR, EVERY, port(8002), OPEN),
        needs=("alpaca",),
        url_port_field="port",
        notes=(
            "Solo opera con el mercado abierto (15:30–22:00 hora de España).",
            "Si la cuenta paper tiene posiciones que no abrió el bot, no arranca.",
        ),
    ),
    Mode(
        "stocks_local",
        "🧪",
        "Acciones · fills simulados",
        "Precios reales de acciones (Alpaca) pero compras y ventas simuladas en local, sin enviar "
        "nada a Alpaca.",
        "Para probar el bot con acciones sin tocar tu cuenta paper.",
        ("run", "--market", "stocks", "--broker", "local"),
        (CASH, AGGR, EVERY, port(8003), OPEN),
        needs=("alpaca",),
        url_port_field="port",
    ),
    Mode(
        "simulate",
        "⏪",
        "Simulación sobre historia real",
        "Reproduce días pasados con el mismo motor que en vivo, a cámara rápida, y compara con "
        "comprar y mantener. Con «aprender» el Research Lab funciona dentro de la simulación.",
        "Para ver en minutos qué habría hecho el bot la última semana.",
        ("simulate",),
        (
            MARKET,
            Field(
                "hours",
                "--hours",
                "Horas de historia",
                "Cuánto tiempo pasado reproducir (168 = una semana).",
                "float",
                168.0,
                minimum=1,
            ),
            Field(
                "cash",
                "--cash",
                "Capital (USD)",
                "Capital inicial de la simulación.",
                "float",
                10_000.0,
                minimum=10,
            ),
            Field(
                "learn",
                "--learn",
                "Aprender durante la simulación",
                "Ejecuta el Research Lab dentro de la simulación, sin mirar el futuro.",
                "bool",
                True,
                off_flag="--no-learn",
            ),
            Field(
                "headless",
                "--headless",
                "Solo resumen (sin dashboard)",
                "Va a máxima velocidad y al final muestra un resumen en la terminal.",
                "bool",
                False,
                off_flag="--no-headless",
            ),
            Field(
                "speed",
                "--speed",
                "Velocidad (× tiempo real)",
                "Lo rápido que avanza en el dashboard. 0 = lo máximo posible.",
                "float",
                300.0,
                minimum=0,
            ),
            port(8001),
            OPEN,
        ),
        url_port_field="port",
    ),
    Mode(
        "research",
        "🔬",
        "Research ahora",
        "Lanza un ciclo completo del Research Lab: prueba miles de reglas con historia real y "
        "solo da por buenas las que superan todos los exámenes estadísticos. No opera.",
        "Para buscar reglas nuevas sin esperar al ciclo automático (tarda de 5 a 20 minutos).",
        ("research",),
        (
            MARKET,
            Field(
                "days",
                "--days",
                "Días de historia",
                "Más días = más muestra y resultados más fiables (365 recomendado).",
                "float",
                365.0,
                minimum=7,
            ),
            Field(
                "timeframes",
                "--timeframes",
                "Escalas de tiempo",
                "Vacío = las del mercado (cripto 1min,1h,4h,1d; acciones 15min,1h,1d).",
                "text",
                "",
            ),
            Field(
                "analyst",
                "--analyst",
                "Preguntar antes al analista IA",
                "Pide ideas nuevas a la IA (unos 5 céntimos) y el lab las examina.",
                "bool",
                True,
                off_flag="--no-analyst",
            ),
        ),
    ),
    Mode(
        "analyst",
        "🤖",
        "Analista IA",
        "Pide a la IA hipótesis nuevas a partir de lo que el lab ha aprendido. Solo propone: "
        "las ideas se examinan en el siguiente ciclo de research. Nunca opera.",
        "Para darle ideas al lab entre ciclos, o ver qué leería la IA (modo prueba, gratis).",
        ("analyst",),
        (
            MARKET,
            Field(
                "dry_run",
                "--dry-run",
                "Solo ver qué leería (gratis)",
                "Muestra el contexto que se enviaría a la IA sin llamarla.",
                "bool",
                True,
                off_flag="--no-dry-run",
            ),
        ),
        needs=("openai",),
    ),
    Mode(
        "news",
        "📰",
        "Noticias del día",
        "La IA lee los titulares reales de las últimas 24 h (Alpaca News) sabiendo qué día es, "
        "resume lo importante y propone hipótesis que el lab examinará. Nunca opera.",
        "Para empezar el día sabiendo qué noticias mueven el mercado (el trader lo hace solo "
        "a las 8:45 de Nueva York, 14:45 en España).",
        ("news",),
        (
            Field(
                "market",
                "--market",
                "Mercado",
                "Acciones: además de las noticias generales, las de los valores que opera el bot.",
                "choice",
                "stocks",
                (("stocks", "Acciones · EE. UU."), ("binance", "Cripto · Binance")),
            ),
            Field(
                "dry_run",
                "--dry-run",
                "Solo ver los titulares (gratis)",
                "Muestra la fecha y los titulares que leería la IA, sin llamarla.",
                "bool",
                True,
                off_flag="--no-dry-run",
            ),
            Field(
                "force",
                "--force",
                "Rehacer el de hoy",
                "Genera un resumen nuevo aunque ya exista el de hoy (gasta una llamada).",
                "bool",
                False,
                off_flag="--no-force",
            ),
        ),
        needs=("alpaca", "openai"),
        notes=("Los titulares son de Alpaca News: hacen falta las claves paper de Alpaca.",),
    ),
)

MODE_BY_KEY = {m.key: m for m in MODES}


def defaults(mode: Mode) -> dict[str, Value]:
    return {f.key: f.default for f in mode.fields}


def validate(mode: Mode, values: Mapping[str, Value]) -> dict[str, str]:
    """Field key → problem, for every value that cannot be used."""
    errors: dict[str, str] = {}
    for f in mode.fields:
        v = values.get(f.key, f.default)
        if f.kind in ("int", "float"):
            try:
                x = float(v)
            except (TypeError, ValueError):
                errors[f.key] = "tiene que ser un número"
                continue
            if f.kind == "int" and x != int(x):
                errors[f.key] = "tiene que ser un número entero"
            elif f.minimum is not None and x < f.minimum:
                errors[f.key] = f"mínimo {f.minimum:g}"
            elif f.maximum is not None and x > f.maximum:
                errors[f.key] = f"máximo {f.maximum:g}"
        elif f.kind == "choice" and v not in {c for c, _ in f.choices}:
            errors[f.key] = "opción no válida"
        elif f.kind == "text" and any(ch.isspace() for ch in str(v).strip()):
            errors[f.key] = "sin espacios (separa con comas)"
    return errors


def fmt_value(f: Field, v: Value) -> str:
    if f.kind == "int":
        return str(int(float(v)))
    if f.kind == "float":
        x = float(v)
        return str(int(x)) if x == int(x) else f"{x:g}"
    return str(v).strip()


def build_args(mode: Mode, values: Mapping[str, Value]) -> list[str]:
    """Arguments for ``python -m services.trader`` (explicit: what you see is what runs)."""
    args = list(mode.fixed)
    for f in mode.fields:
        v = values.get(f.key, f.default)
        if f.kind == "bool":
            args.append(f.flag if v else f.off_flag)
        elif f.kind == "text" and not str(v).strip():
            continue  # empty = the CLI's own default
        else:
            args += [f.flag, fmt_value(f, v)]
    return args


def dashboard_url(mode: Mode, values: Mapping[str, Value]) -> str | None:
    if not mode.url_port_field:
        return None
    p = values.get(mode.url_port_field)
    f = next(x for x in mode.fields if x.key == mode.url_port_field)
    return f"http://127.0.0.1:{int(float(p if p is not None else f.default))}"


@dataclass(frozen=True)
class Readiness:
    alpaca: bool
    openai: bool
    notify: bool

    def missing(self, mode: Mode) -> list[str]:
        out = []
        if "alpaca" in mode.needs and not self.alpaca:
            out.append("Faltan las claves de Alpaca paper en .env (ALPACA_KEY_PAPER y su secreto).")
        if "openai" in mode.needs and not self.openai:
            out.append("Falta OPENAI_API_KEY en .env.")
        return out


def readiness(env: Mapping[str, str] | None = None) -> Readiness:
    """Which keys are configured (never their values)."""
    from aqt.stream.alpaca import alpaca_credentials

    env = os.environ if env is None else env
    return Readiness(
        alpaca=alpaca_credentials(env) is not None,
        openai=bool(env.get("OPENAI_API_KEY", "").strip()),
        notify=bool(env.get("NOTIFY_WEBHOOK_URL", "").strip()),
    )
