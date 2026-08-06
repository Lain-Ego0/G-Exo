"""Read-only FastAPI application for real IMU telemetry."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import time
from typing import Callable, Protocol

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .imu_cache import ImuTelemetryCache
from .schemas import ImuReading, JointId

logger = logging.getLogger(__name__)


class ImuTransport(Protocol):
    def set_sample_callback(
        self,
        callback: Callable[[JointId, ImuReading, float, float], None],
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class TelemetryHub:
    def __init__(self, publish_hz: float, heartbeat_ms: int) -> None:
        self._interval_s = 1.0 / max(1.0, publish_hz)
        self._heartbeat_s = max(heartbeat_ms, 50) / 1000.0
        self._clients: set[WebSocket] = set()
        self._dirty = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._snapshot: Callable[[], dict] | None = None

    def start(self, snapshot: Callable[[], dict]) -> None:
        self._loop = asyncio.get_running_loop()
        self._snapshot = snapshot
        self._task = self._loop.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def mark_dirty_threadsafe(self) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._mark_dirty)

    def _mark_dirty(self) -> None:
        self._dirty = True

    async def register(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        if self._snapshot is not None:
            await websocket.send_json(self._snapshot())

    def unregister(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def _run(self) -> None:
        last_broadcast = 0.0
        while True:
            await asyncio.sleep(self._interval_s)
            now = time.monotonic()
            heartbeat_due = now - last_broadcast >= self._heartbeat_s
            if not self._clients or (not self._dirty and not heartbeat_due):
                continue
            self._dirty = False
            last_broadcast = now
            if self._snapshot is None:
                continue
            payload = self._snapshot()
            dead: list[WebSocket] = []
            for websocket in list(self._clients):
                try:
                    await websocket.send_json(payload)
                except Exception:
                    dead.append(websocket)
            for websocket in dead:
                self._clients.discard(websocket)


def create_telemetry_app(
    settings: Settings,
    cache: ImuTelemetryCache,
    transport: ImuTransport,
    control_app: FastAPI | None = None,
) -> FastAPI:
    telemetry = settings.telemetry
    hub = TelemetryHub(telemetry.ws_publish_hz, telemetry.heartbeat_ms)

    def snapshot_payload() -> dict:
        return cache.snapshot().model_dump(mode="json")

    def on_sample(
        joint: JointId,
        reading: ImuReading,
        received_wall_ms: float,
        received_monotonic: float,
    ) -> None:
        cache.update(joint, reading, received_wall_ms, received_monotonic)
        hub.mark_dirty_threadsafe()

    transport.set_sample_callback(on_sample)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.start(snapshot_payload)
        transport.start()
        control_lifespan = (
            control_app.router.lifespan_context(control_app)
            if control_app is not None
            else None
        )
        if control_lifespan is not None:
            await control_lifespan.__aenter__()
        logger.info("read-only IMU telemetry application started")
        try:
            yield
        finally:
            if control_lifespan is not None:
                await control_lifespan.__aexit__(None, None, None)
            await hub.stop()
            transport.stop()

    app = FastAPI(title="G-Exo IMU Telemetry", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        envelope = cache.snapshot()
        return {
            "status": "ok",
            "mode": "telemetry_only",
            "transport": "ros2_imu",
            "overall_status": envelope.overall_status,
        }

    @app.get("/api/telemetry")
    async def get_telemetry() -> dict:
        return snapshot_payload()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await hub.register(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(websocket)

    # The control surface remains deliberately namespaced: values below
    # /control are simulated and must never be mistaken for ROS telemetry.
    if control_app is not None:
        app.mount("/control", control_app, name="simulated-control")

    static_dir = Path(__file__).resolve().parent.parent / "static"
    if (static_dir / "index.html").is_file():
        @app.get("/ring", include_in_schema=False)
        @app.get("/cockpit", include_in_schema=False)
        async def frontend_entry() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
