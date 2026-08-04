"""FastAPI application: HTTP API + WebSocket state push.

The app factory wires together the already-constructed core objects
(StateCache / CommandManager / RosBridgeAdapter).  The chat pipeline is
injected as an optional `ChatHandler` so the API layer has no LLM imports;
until Phase 7 wires the intent router in, /api/chat degrades gracefully.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .command_manager import CommandManager
from .config import Settings
from .logging_config import control_event
from .mock_controller_core import SCENARIOS, MockControllerCore
from .ros_bridge import RosBridgeAdapter
from .schemas import (
    ActionEnvelope,
    ActionRequest,
    ChatRequest,
    ChatResponse,
    CommandStatus,
    ConfirmRequest,
    ErrorCode,
    StateResponse,
)
from .state_cache import StateCache

logger = logging.getLogger(__name__)

ChatHandler = Callable[[str], Awaitable[ChatResponse]]


class WsHub:
    """Coalescing state broadcaster.

    The transport thread marks the hub dirty (via call_soon_threadsafe); a
    single broadcast task wakes up, snapshots the cache once and fans out to
    every connected socket, at most once per `min_interval_ms`.  A slow phone
    can therefore never build an unbounded backlog.
    """

    def __init__(self, min_interval_ms: int = 200) -> None:
        self._dirty = asyncio.Event()
        self._min_interval = min_interval_ms / 1000.0
        self._clients: set[WebSocket] = set()
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._snapshot_fn: Optional[Callable[[], dict[str, Any]]] = None

    def start(self, loop: asyncio.AbstractEventLoop, snapshot_fn: Callable[[], dict[str, Any]]) -> None:
        self._loop = loop
        self._snapshot_fn = snapshot_fn
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def mark_dirty_threadsafe(self) -> None:
        """Callable from any thread."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._dirty.set)

    async def register(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        # greet with the current snapshot so the UI paints immediately
        if self._snapshot_fn is not None:
            try:
                await ws.send_json(self._snapshot_fn())
            except Exception:
                self._clients.discard(ws)

    def unregister(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def _run(self) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            if self._clients and self._snapshot_fn is not None:
                payload = self._snapshot_fn()
                dead: list[WebSocket] = []
                for ws in list(self._clients):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    self._clients.discard(ws)
            await asyncio.sleep(self._min_interval)


def _state_payload(cache: StateCache) -> dict[str, Any]:
    state = cache.get()
    stale = cache.is_stale()
    return StateResponse(
        online=state is not None and not stale,
        stale=stale,
        state=state,
        last_update_ms=cache.last_update_ms(),
    ).model_dump(mode="json")


def create_app(
    settings: Settings,
    cache: StateCache,
    bridge: RosBridgeAdapter,
    commands: CommandManager,
    chat_handler: Optional[ChatHandler] = None,
    mock_core: Optional[MockControllerCore] = None,
) -> FastAPI:
    hub = WsHub(min_interval_ms=settings.state.ws_min_interval_ms)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        commands.set_event_loop(loop)
        hub.start(loop, lambda: _state_payload(cache))
        bridge.on_state(lambda msg: (cache.update(msg.data), hub.mark_dirty_threadsafe()))
        bridge.start()
        logger.info("web agent started (transport=%s)", settings.bridge.transport)
        try:
            yield
        finally:
            await hub.stop()
            bridge.stop()

    app = FastAPI(title="G-Exo Web Agent", version="0.1.0", lifespan=lifespan)
    app.state.hub = hub
    app.state.chat_handler = chat_handler

    # ------------------------------------------------------------- endpoints

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "transport": settings.bridge.transport,
            "state_online": not cache.is_stale(),
        }

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        return _state_payload(cache)

    @app.post("/api/action")
    async def post_action(body: ActionRequest) -> JSONResponse:
        """Explicit-button endpoint: no NL parsing, same SafetyGuard."""
        try:
            action = ActionEnvelope.parse_untrusted({"action": body.action, **body.params})
        except Exception:
            raise HTTPException(status_code=422, detail="未定义或参数非法的操作")

        if action.action == "query_status":
            return JSONResponse(_state_payload(cache))
        if action.action == "document_qa":
            raise HTTPException(status_code=422, detail="document_qa 请使用 /api/chat")

        control_event("action_request", source="button", action=action.action,
                      params=action.model_dump(exclude={"action"}))
        view = await commands.submit(action)
        status_code = 200
        if view.status is CommandStatus.REJECTED and view.error_code == ErrorCode.BUSY.value:
            status_code = 409
        return JSONResponse(view.model_dump(mode="json"), status_code=status_code)

    @app.post("/api/confirm")
    async def post_confirm(body: ConfirmRequest) -> JSONResponse:
        view = await commands.confirm(body.request_id, body.approve)
        if view is None:
            raise HTTPException(status_code=404, detail="未知的 request_id")
        return JSONResponse(view.model_dump(mode="json"))

    @app.get("/api/action/{request_id}")
    async def get_action(request_id: str) -> JSONResponse:
        view = commands.get_view(request_id)
        if view is None:
            raise HTTPException(status_code=404, detail="未知的 request_id")
        return JSONResponse(view.model_dump(mode="json"))

    @app.post("/api/chat")
    async def post_chat(body: ChatRequest) -> JSONResponse:
        handler: Optional[ChatHandler] = app.state.chat_handler
        if handler is None:
            return JSONResponse(
                ChatResponse(
                    reply="智能对话功能尚未接入，请使用页面按钮操作。",
                    intent="unavailable",
                ).model_dump(mode="json"),
                status_code=503,
            )
        control_event("chat_request", text=body.text)
        response = await handler(body.text)
        return JSONResponse(response.model_dump(mode="json"))

    # -------------------------------------------------------------- debug

    if settings.debug.enabled and mock_core is not None:

        @app.post("/api/debug/scenario")
        async def set_scenario(body: dict[str, str]) -> dict[str, str]:
            scenario = body.get("scenario", "")
            if scenario not in SCENARIOS:
                raise HTTPException(status_code=422, detail=f"未知场景，可选: {SCENARIOS}")
            mock_core.set_scenario(scenario)
            return {"scenario": scenario}

        @app.get("/api/debug/scenario")
        async def get_scenario() -> dict[str, Any]:
            return {"scenario": mock_core.get_scenario(), "available": list(SCENARIOS)}

    # ----------------------------------------------------------- websocket

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.register(ws)
        try:
            while True:
                # we only push; incoming frames are ping/keepalive
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(ws)

    # ------------------------------------------------------------- static

    static_dir = Path(__file__).resolve().parent.parent / "static"
    if (static_dir / "index.html").is_file():
        @app.get("/ring", include_in_schema=False)
        @app.get("/cockpit", include_in_schema=False)
        async def frontend_entry() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
