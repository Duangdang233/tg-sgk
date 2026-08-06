from __future__ import annotations

import abc
import asyncio
import hashlib
import itertools
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.errors import (
    ButtonNotFoundError,
    MessageNotFoundError,
    TargetNotBotError,
    TargetNotFoundError,
    WaitTimeoutError,
)
from app.schemas import BotInfo, ButtonInfo, MessageInfo


def message_signature(text: str, buttons: list[ButtonInfo]) -> str:
    payload = text + "|" + "|".join(
        f"{button.row}:{button.column}:{button.text}:{button.url or ''}" for button in buttons
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


class TelegramAdapter(abc.ABC):
    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    @abc.abstractmethod
    async def status(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def inspect_bot(self, target: str) -> BotInfo: ...

    @abc.abstractmethod
    async def send_message(self, target: str, text: str) -> MessageInfo: ...

    @abc.abstractmethod
    async def recent_messages(self, target: str, limit: int = 10) -> list[MessageInfo]: ...

    @abc.abstractmethod
    async def click_button(
        self,
        target: str,
        message_id: int,
        *,
        text: str | None = None,
        row: int | None = None,
        column: int | None = None,
    ) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def wait_for_update(
        self,
        target: str,
        *,
        after_message_id: int | None,
        watch_message_id: int | None,
        previous_signature: str | None,
        timeout_seconds: float,
    ) -> MessageInfo: ...


class MockTelegramAdapter(TelegramAdapter):
    """Deterministic in-memory adapter for tests and local smoke runs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._started = False
        self._ids = itertools.count(1)
        self._messages: dict[str, list[MessageInfo]] = {}
        self._condition = asyncio.Condition()

    async def start(self) -> None:
        self._started = True

    async def close(self) -> None:
        self._started = False

    async def status(self) -> dict[str, Any]:
        return {"mode": "mock", "connected": self._started, "authorized": True}

    async def inspect_bot(self, target: str) -> BotInfo:
        normalized = self._normalize(target)
        if normalized in {"@human", "@channel", "@group"} or not normalized.lower().endswith(
            "bot"
        ):
            raise TargetNotBotError(f"target is not a bot: {target}")
        return BotInfo(
            target=normalized,
            id=abs(hash(normalized)) % 10_000_000,
            username=normalized[1:],
            display_name=normalized[1:],
            is_bot=True,
        )

    async def send_message(self, target: str, text: str) -> MessageInfo:
        await self.inspect_bot(target)
        normalized = self._normalize(target)
        outgoing = self._make_message(text=text, outgoing=True)
        self._messages.setdefault(normalized, []).append(outgoing)

        if text.strip().lower() == "/start":
            response = self._make_message(
                text="欢迎使用，请选择操作",
                outgoing=False,
                buttons=[
                    ButtonInfo(row=0, column=0, text="账户"),
                    ButtonInfo(row=1, column=0, text="每日签到"),
                ],
            )
        elif text.strip().lower() in {"/checkin", "签到"}:
            response = self._make_message(text="签到成功，获得 10 积分", outgoing=False)
        else:
            response = self._make_message(
                text=f"机器人收到：{text}",
                outgoing=False,
                buttons=[ButtonInfo(row=0, column=0, text="每日签到")],
            )
        self._messages[normalized].append(response)
        async with self._condition:
            self._condition.notify_all()
        return outgoing

    async def recent_messages(self, target: str, limit: int = 10) -> list[MessageInfo]:
        await self.inspect_bot(target)
        normalized = self._normalize(target)
        messages = self._messages.get(normalized, [])
        return list(reversed(messages[-limit:]))

    async def click_button(
        self,
        target: str,
        message_id: int,
        *,
        text: str | None = None,
        row: int | None = None,
        column: int | None = None,
    ) -> dict[str, Any]:
        await self.inspect_bot(target)
        normalized = self._normalize(target)
        message = next(
            (item for item in self._messages.get(normalized, []) if item.id == message_id), None
        )
        if message is None:
            raise MessageNotFoundError(f"message not found: {message_id}")

        selected = None
        for button in message.buttons:
            if text is not None and button.text == text:
                selected = button
                break
            if row is not None and column is not None and button.row == row and button.column == column:
                selected = button
                break
        if selected is None:
            raise ButtonNotFoundError("button selector did not match")

        if "签到" in selected.text:
            response_text = "签到成功，获得 10 积分"
        elif selected.text == "账户":
            response_text = "账户中心"
        else:
            response_text = f"已点击：{selected.text}"

        response = self._make_message(text=response_text, outgoing=False)
        self._messages.setdefault(normalized, []).append(response)
        async with self._condition:
            self._condition.notify_all()
        return {"clicked": selected.model_dump(), "response": response.model_dump()}

    async def wait_for_update(
        self,
        target: str,
        *,
        after_message_id: int | None,
        watch_message_id: int | None,
        previous_signature: str | None,
        timeout_seconds: float,
    ) -> MessageInfo:
        await self.inspect_bot(target)
        normalized = self._normalize(target)

        def find_update() -> MessageInfo | None:
            messages = self._messages.get(normalized, [])
            if after_message_id is not None:
                for message in reversed(messages):
                    if not message.outgoing and message.id > after_message_id:
                        return message
            if watch_message_id is not None:
                watched = next((m for m in messages if m.id == watch_message_id), None)
                if watched and previous_signature and watched.signature != previous_signature:
                    return watched
            return None

        existing = find_update()
        if existing:
            return existing
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self._condition:
                    while True:
                        await self._condition.wait()
                        found = find_update()
                        if found:
                            return found
        except TimeoutError as exc:
            raise WaitTimeoutError("timed out waiting for bot update") from exc

    def _make_message(
        self, *, text: str, outgoing: bool, buttons: list[ButtonInfo] | None = None
    ) -> MessageInfo:
        button_list = buttons or []
        now = datetime.now(UTC).isoformat()
        return MessageInfo(
            id=next(self._ids),
            text=text,
            outgoing=outgoing,
            date=now,
            buttons=button_list,
            signature=message_signature(text, button_list),
        )

    @staticmethod
    def _normalize(target: str) -> str:
        value = target.strip()
        if not value:
            raise TargetNotFoundError("empty target")
        return value if value.startswith("@") else f"@{value}"
