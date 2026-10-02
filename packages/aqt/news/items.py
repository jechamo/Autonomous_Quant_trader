"""A news headline as the lab sees it: when it was published, about whom, and what kind."""

from __future__ import annotations

from dataclasses import dataclass

from aqt.news.classify import classify_headline


@dataclass(frozen=True)
class NewsItem:
    id: int
    created_at: float  # epoch seconds of first publication (later edits are ignored)
    headline: str
    symbols: tuple[str, ...]
    source: str = ""
    url: str = ""
    summary: str = ""

    @property
    def kind(self) -> str:
        return classify_headline(self.headline)
