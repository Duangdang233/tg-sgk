from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.errors import FlowNotFoundError
from app.schemas import FlowCreate, FlowRecord, RunRecord


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS flows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                bot TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                target TEXT,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result_json TEXT,
                error_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS runs_created_at_idx ON runs(created_at DESC);
            CREATE INDEX IF NOT EXISTS runs_target_idx ON runs(target);
            """
        )
        self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("database is not connected")
        return self._connection

    async def upsert_flow(self, flow: FlowCreate) -> FlowRecord:
        now = utc_now_iso()
        steps_json = json.dumps(
            [step.model_dump(exclude_none=True) for step in flow.steps], ensure_ascii=False
        )
        async with self._lock:
            existing = self.connection.execute(
                "SELECT created_at FROM flows WHERE id = ?", (flow.id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            self.connection.execute(
                """
                INSERT INTO flows(id, name, bot, steps_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    bot=excluded.bot,
                    steps_json=excluded.steps_json,
                    updated_at=excluded.updated_at
                """,
                (flow.id, flow.name, flow.bot, steps_json, created_at, now),
            )
            self.connection.commit()
        return await self.get_flow(flow.id)

    async def list_flows(self) -> list[FlowRecord]:
        async with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM flows ORDER BY id ASC"
            ).fetchall()
        return [self._row_to_flow(row) for row in rows]

    async def get_flow(self, flow_id: str) -> FlowRecord:
        async with self._lock:
            row = self.connection.execute(
                "SELECT * FROM flows WHERE id = ?", (flow_id,)
            ).fetchone()
        if row is None:
            raise FlowNotFoundError(f"flow not found: {flow_id}")
        return self._row_to_flow(row)

    async def delete_flow(self, flow_id: str) -> None:
        async with self._lock:
            cursor = self.connection.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
            self.connection.commit()
        if cursor.rowcount == 0:
            raise FlowNotFoundError(f"flow not found: {flow_id}")

    def _row_to_flow(self, row: sqlite3.Row) -> FlowRecord:
        return FlowRecord(
            id=row["id"],
            name=row["name"],
            bot=row["bot"],
            steps=json.loads(row["steps_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def create_run(
        self, *, task_type: str, target: str | None, priority: int
    ) -> RunRecord:
        run_id = uuid.uuid4().hex
        created_at = utc_now_iso()
        async with self._lock:
            self.connection.execute(
                """
                INSERT INTO runs(id, task_type, target, priority, status, created_at)
                VALUES(?, ?, ?, ?, 'queued', ?)
                """,
                (run_id, task_type, target, priority, created_at),
            )
            self.connection.commit()
        return await self.get_run(run_id)

    async def mark_run_started(self, run_id: str) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE runs SET status='running', started_at=? WHERE id=?",
                (utc_now_iso(), run_id),
            )
            self.connection.commit()

    async def mark_run_succeeded(self, run_id: str, result: Any) -> None:
        async with self._lock:
            self.connection.execute(
                """
                UPDATE runs
                SET status='succeeded', finished_at=?, result_json=?, error_json=NULL
                WHERE id=?
                """,
                (utc_now_iso(), json.dumps(_jsonable(result), ensure_ascii=False, default=str), run_id),
            )
            self.connection.commit()

    async def mark_run_failed(self, run_id: str, error: dict[str, Any]) -> None:
        async with self._lock:
            self.connection.execute(
                """
                UPDATE runs
                SET status='failed', finished_at=?, error_json=?
                WHERE id=?
                """,
                (utc_now_iso(), json.dumps(error, ensure_ascii=False, default=str), run_id),
            )
            self.connection.commit()

    async def get_run(self, run_id: str) -> RunRecord:
        async with self._lock:
            row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._row_to_run(row)

    async def list_runs(self, *, limit: int = 50, target: str | None = None) -> list[RunRecord]:
        query = "SELECT * FROM runs"
        params: list[Any] = []
        if target:
            query += " WHERE target = ?"
            params.append(target)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        async with self._lock:
            rows = self.connection.execute(query, params).fetchall()
        return [self._row_to_run(row) for row in rows]

    def _row_to_run(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            task_type=row["task_type"],
            target=row["target"],
            priority=row["priority"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=json.loads(row["error_json"]) if row["error_json"] else None,
            created_at=row["created_at"],
        )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
