from __future__ import annotations

import asyncio
from datetime import UTC
from typing import Any

from app.config import Settings
from app.errors import (
    ButtonNotFoundError,
    MessageNotFoundError,
    TargetNotBotError,
    TargetNotFoundError,
    TelegramAuthorizationRequiredError,
    TelegramNotConfiguredError,
    WaitTimeoutError,
)
from app.schemas import BotInfo, ButtonInfo, MessageInfo
from app.telegram_adapter import TelegramAdapter, message_signature


class TelethonTelegramAdapter(TelegramAdapter):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Any | None = None
        self._action_lock = asyncio.Lock()
        self._last_action_at = 0.0

    async def start(self) -> None:
        if not self.settings.tg_api_id or not self.settings.tg_api_hash:
            raise TelegramNotConfiguredError("TG_API_ID and TG_API_HASH are required")

        from telethon import TelegramClient

        self.client = TelegramClient(
            self.settings.tg_session_path,
            self.settings.tg_api_id,
            self.settings.tg_api_hash,
        )
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.disconnect()
            self.client = None
            raise TelegramAuthorizationRequiredError(
                "Telegram session is not authorized; run `python -m app.login` first"
            )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.disconnect()
            self.client = None

    async def status(self) -> dict[str, Any]:
        if self.client is None:
            return {"mode": "telethon", "connected": False, "authorized": False}
        connected = self.client.is_connected()
        authorized = await self.client.is_user_authorized() if connected else False
        me = await self.client.get_me() if authorized else None
        return {
            "mode": "telethon",
            "connected": connected,
            "authorized": authorized,
            "user_id": getattr(me, "id", None),
            "username": getattr(me, "username", None),
        }

    async def inspect_bot(self, target: str) -> BotInfo:
        entity = await self._get_bot_entity(target)
        display_name = " ".join(
            part for part in [getattr(entity, "first_name", None), getattr(entity, "last_name", None)] if part
        ) or getattr(entity, "username", None)
        return BotInfo(
            target=self._normalize_target(target),
            id=int(entity.id),
            username=getattr(entity, "username", None),
            display_name=display_name,
            is_bot=True,
        )

    async def send_message(self, target: str, text: str) -> MessageInfo:
        entity = await self._get_bot_entity(target)
        async with self._action_lock:
            await self._throttle()
            message = await self._require_client().send_message(entity, text)
        return self._serialize_message(message)

    async def recent_messages(self, target: str, limit: int = 10) -> list[MessageInfo]:
        entity = await self._get_bot_entity(target)
        messages = await self._require_client().get_messages(entity, limit=limit)
        return [self._serialize_message(message) for message in messages]

    async def click_button(
        self,
        target: str,
        message_id: int,
        *,
        text: str | None = None,
        row: int | None = None,
        column: int | None = None,
    ) -> dict[str, Any]:
        entity = await self._get_bot_entity(target)
        message = await self._require_client().get_messages(entity, ids=message_id)
        if message is None:
            raise MessageNotFoundError(f"message not found: {message_id}")
        buttons = self._extract_buttons(message)
        selected = None
        for button in buttons:
            if text is not None and button.text == text:
                selected = button
                break
            if row is not None and column is not None and button.row == row and button.column == column:
                selected = button
                break
        if selected is None:
            raise ButtonNotFoundError("button selector did not match")

        async with self._action_lock:
            await self._throttle()
            if text is not None:
                result = await message.click(text=text)
            else:
                result = await message.click(i=row, j=column)

        serialized_result: Any
        if hasattr(result, "to_dict"):
            serialized_result = result.to_dict()
        elif isinstance(result, bytes):
            serialized_result = result.hex()
        else:
            serialized_result = str(result) if result is not None else None
        return {"clicked": selected.model_dump(), "callback_result": serialized_result}

    async def wait_for_update(
        self,
        target: str,
        *,
        after_message_id: int | None,
        watch_message_id: int | None,
        previous_signature: str | None,
        timeout_seconds: float,
    ) -> MessageInfo:
        entity = await self._get_bot_entity(target)
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            messages = await self._require_client().get_messages(entity, limit=10)
            for message in messages:
                serialized = self._serialize_message(message)
                if (
                    after_message_id is not None
                    and not serialized.outgoing
                    and serialized.id > after_message_id
                ):
                    return serialized
                if (
                    watch_message_id is not None
                    and serialized.id == watch_message_id
                    and previous_signature
                    and serialized.signature != previous_signature
                ):
                    return serialized
            await asyncio.sleep(0.8)
        raise WaitTimeoutError("timed out waiting for bot update")

    async def _get_bot_entity(self, target: str) -> Any:
        client = self._require_client()
        normalized = self._normalize_target(target)
        try:
            entity = await client.get_entity(normalized)
        except (ValueError, TypeError) as exc:
            raise TargetNotFoundError(f"target not found: {target}") from exc
        if not bool(getattr(entity, "bot", False)):
            raise TargetNotBotError(f"target is not a bot: {target}")
        return entity

    def _require_client(self) -> Any:
        if self.client is None or not self.client.is_connected():
            raise TelegramAuthorizationRequiredError("Telegram client is not connected")
        return self.client

    async def _throttle(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        wait_for = self.settings.min_action_interval_seconds - (now - self._last_action_at)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        self._last_action_at = loop.time()

    @staticmethod
    def _normalize_target(target: str) -> str:
        value = target.strip()
        if not value:
            raise TargetNotFoundError("empty target")
        return value if value.startswith("@") else f"@{value}"

    def _serialize_message(self, message: Any) -> MessageInfo:
        buttons = self._extract_buttons(message)
        date = getattr(message, "date", None)
        edited = getattr(message, "edit_date", None)
        if date is not None and date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        if edited is not None and edited.tzinfo is None:
            edited = edited.replace(tzinfo=UTC)
        text = getattr(message, "raw_text", None) or getattr(message, "message", None) or ""
        return MessageInfo(
            id=int(message.id),
            text=text,
            outgoing=bool(getattr(message, "out", False)),
            date=date.isoformat() if date else "",
            edited_at=edited.isoformat() if edited else None,
            buttons=buttons,
            signature=message_signature(text, buttons),
        )

    @staticmethod
    def _extract_buttons(message: Any) -> list[ButtonInfo]:
        result: list[ButtonInfo] = []
        rows = getattr(message, "buttons", None) or []
        for row_index, row_buttons in enumerate(rows):
            for column_index, button in enumerate(row_buttons):
                result.append(
                    ButtonInfo(
                        row=row_index,
                        column=column_index,
                        text=getattr(button, "text", "") or "",
                        kind=button.__class__.__name__,
                        url=getattr(button, "url", None),
                    )
                )
        return result
