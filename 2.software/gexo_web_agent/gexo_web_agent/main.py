"""Application entry point.

    python -m gexo_web_agent.main [--config PATH] [--transport mock|ros2]
                                  [--host HOST] [--port PORT]

Runs everywhere: with `--transport mock` (default) no ROS 2 installation is
required — the embedded MockController provides the full demo loop.
"""
from __future__ import annotations

import argparse
import logging
from typing import Optional

import uvicorn

from .api import ChatHandler, create_app
from .command_manager import CommandManager
from .config import Settings, load_settings
from .logging_config import setup_logging
from .mock_controller_core import MockControllerCore
from .ros_bridge import MockTransport, Ros2Transport, RosBridgeAdapter
from .state_cache import StateCache

logger = logging.getLogger(__name__)


def build_app(settings: Settings):
    """Construct the full object graph and return the FastAPI app."""
    if settings.telemetry.enabled:
        from .imu_cache import ImuTelemetryCache
        from .imu_transport import ImuRos2Transport
        from .telemetry_api import create_telemetry_app

        telemetry_cache = ImuTelemetryCache(settings.telemetry)
        telemetry_transport = ImuRos2Transport(settings.telemetry.channels)
        control_app = _build_legacy_app(settings, force_mock=True)
        return create_telemetry_app(
            settings, telemetry_cache, telemetry_transport, control_app=control_app
        )

    return _build_legacy_app(settings)


def _build_legacy_app(settings: Settings, force_mock: bool = False):
    """Build the preserved command stack, optionally as a namespaced mock UI."""

    cache = StateCache(stale_timeout_s=settings.state.stale_timeout_s)

    mock_core: Optional[MockControllerCore] = None
    if force_mock or settings.bridge.transport == "mock":
        mock_core = MockControllerCore(scenario=settings.mock.scenario)
        transport = MockTransport(
            mock_core,
            state_hz=settings.mock.state_hz,
            result_latency_ms=settings.mock.result_latency_ms,
        )
    else:
        transport = Ros2Transport(topic=settings.bridge.topic)

    bridge = RosBridgeAdapter(transport, source_id=settings.bridge.source_id)
    commands = CommandManager(
        cache, bridge, settings.safety, settings.command, source_id=settings.bridge.source_id
    )

    chat_handler = _try_build_chat_handler(settings, cache, commands)

    return create_app(
        settings,
        cache,
        bridge,
        commands,
        chat_handler=chat_handler,
        mock_core=mock_core,
    )


def _try_build_chat_handler(
    settings: Settings, cache: StateCache, commands: CommandManager
) -> Optional[ChatHandler]:
    """Wire the LLM chat pipeline if available (Phase 7); degrade otherwise."""
    try:
        from .intent_router import build_chat_handler  # noqa: WPS433
    except ImportError:
        logger.warning("intent_router not available yet; /api/chat disabled")
        return None
    try:
        return build_chat_handler(settings, cache, commands)
    except Exception:
        logger.exception("failed to build chat pipeline; /api/chat disabled")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="G-Exo web agent")
    parser.add_argument("--config", default=None, help="path to YAML config")
    parser.add_argument("--transport", choices=["mock", "ros2"], default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    if args.transport:
        # An explicit legacy transport selection is also the opt-out from the
        # telemetry-only application configured by the shipped YAML.
        settings.telemetry.enabled = False
        settings.bridge.transport = args.transport
    if args.host:
        settings.server.host = args.host
    if args.port:
        settings.server.port = args.port

    setup_logging(settings.logging.level, settings.logging.file)
    if settings.telemetry.enabled:
        logger.info(
            "starting read-only IMU telemetry on %s",
            [channel.topic for channel in settings.telemetry.channels],
        )
    else:
        logger.info(
            "starting legacy gexo_web_agent transport=%s topic=%s",
            settings.bridge.transport,
            settings.bridge.topic,
        )

    app = build_app(settings)
    uvicorn.run(app, host=settings.server.host, port=settings.server.port, log_level="info")


if __name__ == "__main__":
    main()
