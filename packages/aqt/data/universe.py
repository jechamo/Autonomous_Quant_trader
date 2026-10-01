"""Research universes.

Trading 212 from the EU cannot buy US-domiciled ETFs (PRIIPs/KID), so US ETFs are kept only
as long-history *research proxies*. EUR-denominated instruments avoid FX costs, which matter
a lot for a 100 € account.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseInstrument:
    symbol: str  # Yahoo ticker
    name: str
    currency: str
    kind: str  # stock | etf_ucits | etf_us
    tradable_t212_eu: bool


_I = UniverseInstrument

INSTRUMENTS: tuple[UniverseInstrument, ...] = (
    # Research proxies (long history, not buyable from the EU)
    _I("SPY", "SPDR S&P 500", "USD", "etf_us", False),
    _I("QQQ", "Invesco QQQ", "USD", "etf_us", False),
    _I("IWM", "iShares Russell 2000", "USD", "etf_us", False),
    _I("EFA", "iShares MSCI EAFE", "USD", "etf_us", False),
    _I("EEM", "iShares MSCI Emerging Markets", "USD", "etf_us", False),
    _I("TLT", "iShares 20+Y Treasury", "USD", "etf_us", False),
    _I("GLD", "SPDR Gold", "USD", "etf_us", False),
    # UCITS ETFs on Xetra (EUR)
    _I("SXR8.DE", "iShares Core S&P 500 UCITS", "EUR", "etf_ucits", True),
    _I("EUNL.DE", "iShares Core MSCI World UCITS", "EUR", "etf_ucits", True),
    _I("EQQQ.DE", "Invesco Nasdaq-100 UCITS", "EUR", "etf_ucits", True),
    _I("EXS1.DE", "iShares Core DAX UCITS", "EUR", "etf_ucits", True),
    _I("IS3N.DE", "iShares Core MSCI EM IMI UCITS", "EUR", "etf_ucits", True),
    # European stocks (EUR)
    _I("SAN.MC", "Banco Santander", "EUR", "stock", True),
    _I("BBVA.MC", "BBVA", "EUR", "stock", True),
    _I("IBE.MC", "Iberdrola", "EUR", "stock", True),
    _I("ITX.MC", "Inditex", "EUR", "stock", True),
    _I("SAP.DE", "SAP", "EUR", "stock", True),
    _I("SIE.DE", "Siemens", "EUR", "stock", True),
    _I("ALV.DE", "Allianz", "EUR", "stock", True),
    _I("ASML.AS", "ASML", "EUR", "stock", True),
    _I("MC.PA", "LVMH", "EUR", "stock", True),
    _I("TTE.PA", "TotalEnergies", "EUR", "stock", True),
    # US stocks (USD -> FX cost)
    _I("AAPL", "Apple", "USD", "stock", True),
    _I("MSFT", "Microsoft", "USD", "stock", True),
    _I("NVDA", "NVIDIA", "USD", "stock", True),
    _I("AMZN", "Amazon", "USD", "stock", True),
    _I("GOOGL", "Alphabet", "USD", "stock", True),
    _I("META", "Meta Platforms", "USD", "stock", True),
    _I("JPM", "JPMorgan Chase", "USD", "stock", True),
    _I("XOM", "Exxon Mobil", "USD", "stock", True),
    _I("JNJ", "Johnson & Johnson", "USD", "stock", True),
    _I("PG", "Procter & Gamble", "USD", "stock", True),
)

_BY_SYMBOL = {i.symbol: i for i in INSTRUMENTS}

UNIVERSES: dict[str, tuple[str, ...]] = {
    "default": tuple(i.symbol for i in INSTRUMENTS),
    "tradable": tuple(i.symbol for i in INSTRUMENTS if i.tradable_t212_eu),
    "eur": tuple(i.symbol for i in INSTRUMENTS if i.currency == "EUR"),
    "proxies": tuple(i.symbol for i in INSTRUMENTS if not i.tradable_t212_eu),
}


def get_instrument(symbol: str) -> UniverseInstrument:
    """Known instrument, or a conservative default (USD, not marked tradable)."""
    return _BY_SYMBOL.get(symbol, UniverseInstrument(symbol, symbol, "USD", "unknown", False))


def resolve_universe(spec: str) -> list[str]:
    """A named universe (``default``, ``tradable``, ``eur``, ``proxies``) or a comma list."""
    if spec in UNIVERSES:
        return list(UNIVERSES[spec])
    symbols = [s.strip() for s in spec.split(",") if s.strip()]
    if not symbols:
        raise ValueError("empty universe")
    return symbols
