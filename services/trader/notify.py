"""Operator notifications: always logged; optionally pushed to a webhook from ``.env``.

``NOTIFY_WEBHOOK_URL`` may point at ntfy (``https://ntfy.sh/<your-topic>``: free phone push
notifications, plain-text body) or at a Slack/Discord-style webhook (JSON ``text``/``content``).
A failing webhook never affects trading.
"""

from __future__ import annotations

import logging
import os
import ssl
from collections.abc import Callable, Mapping
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

Notifier = Callable[[str, str], None]


def make_notifier(
    env: Mapping[str, str] | None = None, transport: httpx.BaseTransport | None = None
) -> Notifier:
    env = os.environ if env is None else env
    url = env.get("NOTIFY_WEBHOOK_URL", "").strip()

    def notify(title: str, message: str) -> None:
        log.warning("NOTICE %s: %s", title, message)
        if not url:
            return
        kw: dict[str, object] = (
            {"transport": transport}
            if transport is not None
            else {"verify": ssl.create_default_context()}
        )
        try:
            with httpx.Client(timeout=10, **kw) as client:  # type: ignore[arg-type]
                if "ntfy" in (urlparse(url).hostname or ""):
                    r = client.post(
                        url,
                        content=message.encode(),
                        headers={"Title": title.encode("ascii", "ignore").decode()},
                    )
                else:
                    text = f"{title}\n{message}"
                    r = client.post(url, json={"text": text, "content": text})
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("notification webhook failed: %s", exc)

    return notify
