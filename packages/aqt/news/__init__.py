"""Real news headlines turned into causal, deterministic features (see ``aqt.news.book``).

Nothing in this package calls a language model, reads broker accounts or places orders.
"""

from aqt.news.book import NEWS_COLUMNS, NEWS_LAG_S, NewsBook, news_features
from aqt.news.classify import KINDS, classify_headline
from aqt.news.items import NewsItem

__all__ = [
    "KINDS",
    "NEWS_COLUMNS",
    "NEWS_LAG_S",
    "NewsBook",
    "NewsItem",
    "classify_headline",
    "news_features",
]
