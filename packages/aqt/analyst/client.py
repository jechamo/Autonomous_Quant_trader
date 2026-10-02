"""Minimal OpenAI Chat Completions client (JSON output) with a daily call budget."""

from __future__ import annotations

import json
import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

OPENAI_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5-mini"  # cheap reasoning model with JSON mode; override in .env


class AnalystError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalystConfig:
    api_key: str
    model: str
    base_url: str = OPENAI_URL
    max_output_tokens: int = 16000  # reasoning models spend part of it thinking
    timeout_s: float = 120.0
    max_calls_per_day: int = 6
    max_hypotheses: int = 5

    def __repr__(self) -> str:  # never leak the key
        return f"AnalystConfig(model={self.model!r}, base_url={self.base_url!r})"


def analyst_config_from_env(env: Mapping[str, str] | None = None) -> AnalystConfig | None:
    """``OPENAI_API_KEY`` + a model (``OPENAI_MODEL_STRONG``, else ``_CHEAP``, else the default)."""
    env = os.environ if env is None else env
    key = env.get("OPENAI_API_KEY", "").strip()
    model = (
        env.get("OPENAI_MODEL_STRONG", "").strip()
        or env.get("OPENAI_MODEL_CHEAP", "").strip()
        or DEFAULT_MODEL
    )
    if not key:
        return None
    return AnalystConfig(api_key=key, model=model)


@dataclass(frozen=True)
class Completion:
    content: dict[str, Any]
    model: str
    usage: dict[str, Any]


class OpenAIClient:
    def __init__(self, cfg: AnalystConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = cfg
        self._transport = transport

    def __repr__(self) -> str:
        return f"OpenAIClient(model={self.cfg.model!r})"

    def complete_json(self, system: str, user: str) -> Completion:
        body = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": self.cfg.max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        kw: dict[str, Any] = (
            {"transport": self._transport}
            if self._transport is not None
            else {"verify": ssl.create_default_context()}
        )
        with httpx.Client(
            base_url=self.cfg.base_url, headers=headers, timeout=self.cfg.timeout_s, **kw
        ) as c:
            r = c.post("/chat/completions", json=body)
        if r.status_code != 200:
            raise AnalystError(f"OpenAI HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"]
            content = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AnalystError(f"unexpected OpenAI response: {str(data)[:300]}") from exc
        if not isinstance(content, dict):
            raise AnalystError("the model did not return a JSON object")
        return Completion(
            content, str(data.get("model", self.cfg.model)), dict(data.get("usage") or {})
        )
