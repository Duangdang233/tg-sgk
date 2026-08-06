from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.database import Database
from app.errors import TgSgkError
from app.flow_runner import FlowRunner
from app.schemas import (
    BotInspectRequest,
    ClickButtonRequest,
    FlowCreate,
    SendMessageRequest,
    WaitUpdateRequest,
)
from app.security import require_api_key
from app.task_queue import PriorityTaskQueue
from app.telegram_adapter import MockTelegramAdapter, TelegramAdapter
from app.telethon_adapter import TelethonTelegramAdapter

INTERACTIVE_PRIORITY = 100
FLOW_PRIORITY = 10


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime_settings.ensure_directories()
        database = Database(runtime_settings.database_path)
        await database.connect()

        adapter: TelegramAdapter
        if runtime_settings.tg_mock:
            adapter = MockTelegramAdapter(runtime_settings)
        else:
            adapter = TelethonTelegramAdapter(runtime_settings)

        telegram_startup_error: dict[str, Any] | None = None
        try:
            await adapter.start()
        except TgSgkError as exc:
            telegram_startup_error = {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }

        queue = PriorityTaskQueue(database)
        await queue.start()

        app.state.settings = runtime_settings
        app.state.database = database
        app.state.adapter = adapter
        app.state.queue = queue
        app.state.flow_runner = FlowRunner(
            adapter, default_timeout_seconds=runtime_settings.default_timeout_seconds
        )
        app.state.telegram_startup_error = telegram_startup_error
        yield
        await queue.stop()
        await adapter.close()
        await database.close()

    app = FastAPI(
        title="tg-sgk",
        version="0.1.0",
        description="Bot-only Telegram user automation service for OpenClaw",
        lifespan=lifespan,
    )

    @app.exception_handler(TgSgkError)
    async def handle_tg_sgk_error(_request: Request, exc: TgSgkError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            },
        )

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        adapter_status = await request.app.state.adapter.status()
        startup_error = request.app.state.telegram_startup_error
        return {
            "ok": startup_error is None,
            "service": "tg-sgk",
            "version": "0.1.0",
            "telegram": adapter_status,
            "telegram_startup_error": startup_error,
        }

    auth = [Depends(require_api_key)]

    @app.get("/v1/status", dependencies=auth)
    async def status(request: Request) -> dict[str, Any]:
        return {
            "ok": True,
            "data": {
                "telegram": await request.app.state.adapter.status(),
                "startup_error": request.app.state.telegram_startup_error,
            },
        }

    @app.post("/v1/bots/inspect", dependencies=auth)
    async def inspect_bot(payload: BotInspectRequest, request: Request) -> dict[str, Any]:
        target = payload.bot
        result = await request.app.state.queue.submit(
            task_type="inspect_bot",
            target=target,
            priority=INTERACTIVE_PRIORITY,
            operation=lambda: request.app.state.adapter.inspect_bot(target),
        )
        return {"ok": True, "data": _serialize_queue_result(result)}

    @app.post("/v1/messages/send", dependencies=auth)
    async def send_message(payload: SendMessageRequest, request: Request) -> dict[str, Any]:
        result = await request.app.state.queue.submit(
            task_type="send_message",
            target=payload.bot,
            priority=INTERACTIVE_PRIORITY,
            operation=lambda: request.app.state.adapter.send_message(payload.bot, payload.text),
        )
        return {"ok": True, "data": _serialize_queue_result(result)}

    @app.get("/v1/messages/recent", dependencies=auth)
    async def recent_messages(
        request: Request,
        bot: str = Query(min_length=2, max_length=128),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> dict[str, Any]:
        result = await request.app.state.queue.submit(
            task_type="recent_messages",
            target=bot,
            priority=INTERACTIVE_PRIORITY,
            operation=lambda: request.app.state.adapter.recent_messages(bot, limit),
        )
        return {"ok": True, "data": _serialize_queue_result(result)}

    @app.post("/v1/messages/wait", dependencies=auth)
    async def wait_update(payload: WaitUpdateRequest, request: Request) -> dict[str, Any]:
        result = await request.app.state.queue.submit(
            task_type="wait_update",
            target=payload.bot,
            priority=INTERACTIVE_PRIORITY,
            operation=lambda: request.app.state.adapter.wait_for_update(
                payload.bot,
                after_message_id=payload.after_message_id,
                watch_message_id=payload.watch_message_id,
                previous_signature=payload.previous_signature,
                timeout_seconds=payload.timeout_seconds,
            ),
        )
        return {"ok": True, "data": _serialize_queue_result(result)}

    @app.post("/v1/buttons/click", dependencies=auth)
    async def click_button(payload: ClickButtonRequest, request: Request) -> dict[str, Any]:
        result = await request.app.state.queue.submit(
            task_type="click_button",
            target=payload.bot,
            priority=INTERACTIVE_PRIORITY,
            operation=lambda: request.app.state.adapter.click_button(
                payload.bot,
                payload.message_id,
                text=payload.text,
                row=payload.row,
                column=payload.column,
            ),
        )
        return {"ok": True, "data": _serialize_queue_result(result)}

    @app.post("/v1/flows", dependencies=auth)
    async def save_flow(payload: FlowCreate, request: Request) -> dict[str, Any]:
        await request.app.state.queue.submit(
            task_type="inspect_bot",
            target=payload.bot,
            priority=INTERACTIVE_PRIORITY,
            operation=lambda: request.app.state.adapter.inspect_bot(payload.bot),
        )
        flow = await request.app.state.database.upsert_flow(payload)
        return {"ok": True, "data": flow.model_dump()}

    @app.get("/v1/flows", dependencies=auth)
    async def list_flows(request: Request) -> dict[str, Any]:
        flows = await request.app.state.database.list_flows()
        return {"ok": True, "data": [flow.model_dump() for flow in flows]}

    @app.get("/v1/flows/{flow_id}", dependencies=auth)
    async def get_flow(flow_id: str, request: Request) -> dict[str, Any]:
        flow = await request.app.state.database.get_flow(flow_id)
        return {"ok": True, "data": flow.model_dump()}

    @app.delete("/v1/flows/{flow_id}", dependencies=auth)
    async def delete_flow(flow_id: str, request: Request) -> dict[str, Any]:
        await request.app.state.database.delete_flow(flow_id)
        return {"ok": True, "data": {"id": flow_id, "deleted": True}}

    @app.post("/v1/flows/{flow_id}/run", dependencies=auth)
    async def run_flow(flow_id: str, request: Request) -> dict[str, Any]:
        flow = await request.app.state.database.get_flow(flow_id)
        result = await request.app.state.queue.submit(
            task_type="run_flow",
            target=flow.bot,
            priority=FLOW_PRIORITY,
            operation=lambda: request.app.state.flow_runner.run(flow),
        )
        return {"ok": True, "data": _serialize_queue_result(result)}

    @app.get("/v1/history", dependencies=auth)
    async def history(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        target: str | None = Query(default=None, max_length=128),
    ) -> dict[str, Any]:
        runs = await request.app.state.database.list_runs(limit=limit, target=target)
        return {"ok": True, "data": [run.model_dump() for run in runs]}

    return app


def _serialize_queue_result(value: dict[str, Any]) -> dict[str, Any]:
    result = value["result"]
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    elif isinstance(result, list):
        result = [item.model_dump() if hasattr(item, "model_dump") else item for item in result]
    return {"run_id": value["run_id"], "result": result}


app = create_app()
