from __future__ import annotations

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.database import Database
from app.errors import TgSgkError


@dataclass(order=True)
class QueueItem:
    sort_priority: int
    sequence: int
    run_id: str = field(compare=False)
    operation: Callable[[], Awaitable[Any]] = field(compare=False)
    future: asyncio.Future[Any] = field(compare=False)


class PriorityTaskQueue:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._queue: asyncio.PriorityQueue[QueueItem] = asyncio.PriorityQueue()
        self._sequence = itertools.count()
        self._worker: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="tg-sgk-telegram-worker")

    async def stop(self) -> None:
        self._stopping = True
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def submit(
        self,
        *,
        task_type: str,
        target: str | None,
        priority: int,
        operation: Callable[[], Awaitable[Any]],
    ) -> dict[str, Any]:
        run = await self.database.create_run(
            task_type=task_type,
            target=target,
            priority=priority,
        )
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        item = QueueItem(
            sort_priority=-priority,
            sequence=next(self._sequence),
            run_id=run.id,
            operation=operation,
            future=future,
        )
        await self._queue.put(item)
        result = await future
        return {"run_id": run.id, "result": result}

    async def _run(self) -> None:
        while not self._stopping:
            item = await self._queue.get()
            try:
                await self.database.mark_run_started(item.run_id)
                result = await item.operation()
                await self.database.mark_run_succeeded(item.run_id, result)
                if not item.future.done():
                    item.future.set_result(result)
            except Exception as exc:  # noqa: BLE001 - task boundary must record all failures
                if isinstance(exc, TgSgkError):
                    error = {"code": exc.code, "message": exc.message, "details": exc.details}
                else:
                    error = {"code": "INTERNAL_ERROR", "message": str(exc)}
                await self.database.mark_run_failed(item.run_id, error)
                if not item.future.done():
                    item.future.set_exception(exc)
            finally:
                self._queue.task_done()
