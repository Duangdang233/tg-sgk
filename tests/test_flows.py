from __future__ import annotations

import httpx


FLOW = {
    "id": "demo-checkin",
    "name": "Demo daily check-in",
    "bot": "@demo_bot",
    "steps": [
        {"action": "send_message", "text": "/start"},
        {"action": "wait_message", "timeout_seconds": 2},
        {"action": "click_button", "text": "每日签到"},
        {"action": "wait_message_or_edit", "timeout_seconds": 2},
        {"action": "assert_text", "contains_any": ["签到成功", "今日已签到"]},
    ],
}


async def test_save_and_run_flow(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.post("/v1/flows", json=FLOW, headers=auth_headers)
    assert saved.status_code == 200
    assert saved.json()["data"]["id"] == "demo-checkin"

    run = await client.post("/v1/flows/demo-checkin/run", headers=auth_headers)
    assert run.status_code == 200
    result = run.json()["data"]["result"]
    assert result["flow_id"] == "demo-checkin"
    assert "签到成功" in result["final_message"]["text"]

    history = await client.get("/v1/history", headers=auth_headers)
    records = history.json()["data"]
    assert any(record["task_type"] == "run_flow" and record["status"] == "succeeded" for record in records)


async def test_flow_validation_rejects_unsafe_shape(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    invalid = {
        "id": "bad-flow",
        "name": "Bad",
        "bot": "@demo_bot",
        "steps": [{"action": "click_button"}],
    }
    response = await client.post("/v1/flows", json=invalid, headers=auth_headers)
    assert response.status_code == 422


async def test_flow_target_must_be_bot(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    invalid = {**FLOW, "id": "human-flow", "bot": "@human"}
    response = await client.post("/v1/flows", json=invalid, headers=auth_headers)
    assert response.status_code == 403
