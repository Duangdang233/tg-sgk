from __future__ import annotations

import httpx


async def test_health_is_public(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["telegram"]["mode"] == "mock"


async def test_auth_is_required(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_non_bot_target_is_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/bots/inspect", json={"bot": "@human"}, headers=auth_headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TARGET_IS_NOT_A_BOT"


async def test_send_list_and_click_button(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    sent = await client.post(
        "/v1/messages/send",
        json={"bot": "@demo_bot", "text": "/start"},
        headers=auth_headers,
    )
    assert sent.status_code == 200

    recent = await client.get(
        "/v1/messages/recent",
        params={"bot": "@demo_bot", "limit": 10},
        headers=auth_headers,
    )
    assert recent.status_code == 200
    messages = recent.json()["data"]["result"]
    bot_message = next(message for message in messages if not message["outgoing"])
    assert [button["text"] for button in bot_message["buttons"]] == ["账户", "每日签到"]

    clicked = await client.post(
        "/v1/buttons/click",
        json={
            "bot": "@demo_bot",
            "message_id": bot_message["id"],
            "text": "每日签到",
        },
        headers=auth_headers,
    )
    assert clicked.status_code == 200
    result = clicked.json()["data"]["result"]
    assert "签到成功" in result["response"]["text"]
