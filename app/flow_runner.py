from __future__ import annotations

import asyncio
from typing import Any

from app.errors import TgSgkError
from app.schemas import FlowRecord, MessageInfo
from app.telegram_adapter import TelegramAdapter


class FlowRunner:
    def __init__(self, adapter: TelegramAdapter, *, default_timeout_seconds: float) -> None:
        self.adapter = adapter
        self.default_timeout_seconds = default_timeout_seconds

    async def run(self, flow: FlowRecord) -> dict[str, Any]:
        await self.adapter.inspect_bot(flow.bot)
        events: list[dict[str, Any]] = []
        current_message: MessageInfo | None = None

        for index, step in enumerate(flow.steps):
            action = step.action
            if action == "send_message":
                current_message = await self.adapter.send_message(flow.bot, step.text or "")
                events.append(
                    {"step": index, "action": action, "message": current_message.model_dump()}
                )
                continue

            if action in {"wait_message", "wait_message_or_edit"}:
                current_message = await self.adapter.wait_for_update(
                    flow.bot,
                    after_message_id=current_message.id if current_message else None,
                    watch_message_id=(
                        current_message.id if current_message and action == "wait_message_or_edit" else None
                    ),
                    previous_signature=current_message.signature if current_message else None,
                    timeout_seconds=step.timeout_seconds or self.default_timeout_seconds,
                )
                events.append(
                    {"step": index, "action": action, "message": current_message.model_dump()}
                )
                continue

            if action == "click_button":
                if current_message is None:
                    raise TgSgkError("click_button requires a previous message")
                click_result = await self.adapter.click_button(
                    flow.bot,
                    current_message.id,
                    text=step.text,
                    row=step.row,
                    column=step.column,
                )
                events.append({"step": index, "action": action, "result": click_result})
                continue

            if action == "sleep":
                await asyncio.sleep(step.seconds or 0)
                events.append({"step": index, "action": action, "seconds": step.seconds or 0})
                continue

            if action == "assert_text":
                if current_message is None:
                    raise TgSgkError("assert_text requires a previous message")
                expected = step.contains_any or []
                if not any(value in current_message.text for value in expected):
                    raise TgSgkError(
                        "assert_text failed",
                        details={"expected_any": expected, "actual": current_message.text},
                    )
                events.append(
                    {
                        "step": index,
                        "action": action,
                        "matched": next(value for value in expected if value in current_message.text),
                    }
                )
                continue

            raise TgSgkError(f"unsupported flow action: {action}")

        return {
            "flow_id": flow.id,
            "bot": flow.bot,
            "events": events,
            "final_message": current_message.model_dump() if current_message else None,
        }
