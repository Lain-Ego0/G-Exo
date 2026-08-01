"""Minimal OpenAI-compatible chat client for llama-server (llama.cpp).

Only what we need: /chat/completions with optional `tools` or
`response_format`.  No streaming, no SDK dependency — a single httpx call
with a hard timeout so a hung LLM can never block the control path.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from .config import LlmConfig

logger = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """LLM unreachable / bad response.  Callers degrade gracefully."""


class LlmClient:
    def __init__(self, cfg: LlmConfig) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            base_url=cfg.base_url.rstrip("/"),
            timeout=cfg.timeout_s,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """POST /chat/completions; returns the first choice's `message` dict."""
        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "temperature": self._cfg.temperature if temperature is None else temperature,
            "max_tokens": self._cfg.max_tokens if max_tokens is None else max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if response_format:
            payload["response_format"] = response_format

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            body = resp.json()
            return body["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc


def extract_tool_call(message: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
    """Return (tool_name, arguments) from an assistant message, if any."""
    calls = message.get("tool_calls") or []
    if not calls:
        return None
    fn = calls[0].get("function") or {}
    name = fn.get("name", "")
    raw_args = fn.get("arguments", "{}")
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except (json.JSONDecodeError, TypeError):
        logger.warning("unparseable tool arguments: %.200s", raw_args)
        return name, {}
    return name, args if isinstance(args, dict) else {}
