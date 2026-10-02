"""Deterministic headline classifier (keywords, first match wins).

Deterministic on purpose: the same headline always gets the same label, so news features are
reproducible and can be backtested. A language model would "know" what happened after many
historical headlines (it was trained on later text), which would make any backtest optimistic.
"""

from __future__ import annotations

import re

KINDS = ("ipo", "earnings", "guidance", "rating", "m&a", "fda", "legal", "macro", "other")

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.IGNORECASE))
    for kind, pattern in (
        ("ipo", r"\b(ipo|initial public offering|goes public|public debut|lock-?up expir\w*)\b"),
        (
            "earnings",
            r"\b(earnings|eps|quarterly (results|profit|revenue)|"
            r"(q[1-4]|fiscal (q[1-4]|quarter)) (results|revenue|sales|profit|loss))\b",
        ),
        (
            "guidance",
            r"\b(guidance|outlook|(raises|lowers|cuts|boosts|reaffirms) (its |full-year |fy )?"
            r"(forecast|view))\b",
        ),
        (
            "rating",
            r"\b(upgrade[sd]?|downgrade[sd]?|price target|initiates coverage|"
            r"(maintains|reiterates) (buy|hold|sell|overweight|underweight|neutral|outperform))\b",
        ),
        ("m&a", r"\b(acquire[sd]?|acquisition|merger|takeover|buyout|to buy \w+ for)\b"),
        ("fda", r"\b(fda|clinical trial|phase (1|2|3|i|ii|iii) (trial|data|study))\b"),
        ("legal", r"\b(lawsuit|sues|sued|probe|antitrust|subpoena|settles?|settlement)\b"),
        (
            "macro",
            r"\b(fed|fomc|cpi|inflation|jobs report|nonfarm payrolls|gdp|"
            r"interest rates?|treasury yields?|tariffs?)\b",
        ),
    )
)


def classify_headline(text: str) -> str:
    for kind, pattern in _RULES:
        if pattern.search(text):
            return kind
    return "other"
