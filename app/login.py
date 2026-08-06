from __future__ import annotations

import asyncio

from app.config import Settings


async def login() -> None:
    settings = Settings()
    settings.ensure_directories()
    if settings.tg_mock:
        print("TG_MOCK=true: no Telegram login is required.")
        return
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise SystemExit("TG_API_ID and TG_API_HASH must be configured first")

    from telethon import TelegramClient

    client = TelegramClient(settings.tg_session_path, settings.tg_api_id, settings.tg_api_hash)
    await client.start(phone=settings.tg_phone or (lambda: input("Telegram phone: ").strip()))
    me = await client.get_me()
    print(f"Authorized Telegram account: id={me.id}, username={getattr(me, 'username', None)}")
    await client.disconnect()


def main() -> None:
    asyncio.run(login())


if __name__ == "__main__":
    main()
