"""Structured logging for control-related events.

Control events (user input, parsed intent, safety verdict, published command,
controller result, latency, failure reason) are logged as single-line JSON via
`control_event()` so they can be grepped / parsed later.  Free-form LLM chain
of thought and private data must NOT be logged.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional

CONTROL_LOGGER_NAME = "gexo.control"


def setup_logging(level: str = "INFO", file: Optional[str] = None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S"
    )
    handler: logging.Handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    root.handlers.clear()
    root.addHandler(handler)
    if file:
        fh = logging.FileHandler(file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def control_event(event: str, **fields: Any) -> None:
    """Emit a structured control event as one JSON line."""
    payload = {"event": event, **fields}
    logging.getLogger(CONTROL_LOGGER_NAME).info(
        json.dumps(payload, ensure_ascii=False, default=str)
    )
