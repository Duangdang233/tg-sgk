from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        TG_MOCK=True,
        TG_SGK_API_KEY="test-secret-key",
        TG_SGK_DATA_DIR=tmp_path,
        TG_SGK_DATABASE_PATH=tmp_path / "test.sqlite3",
        TG_SESSION_PATH=str(tmp_path / "test-session"),
        TG_SGK_MIN_ACTION_INTERVAL_SECONDS=0,
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-secret-key"}
