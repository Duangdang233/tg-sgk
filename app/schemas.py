from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ButtonInfo(BaseModel):
    row: int
    column: int
    text: str
    kind: str = "callback"
    url: str | None = None


class MessageInfo(BaseModel):
    id: int
    text: str = ""
    outgoing: bool = False
    date: str = Field(default_factory=utc_now_iso)
    edited_at: str | None = None
    buttons: list[ButtonInfo] = Field(default_factory=list)
    signature: str = ""


class BotInfo(BaseModel):
    target: str
    id: int
    username: str | None = None
    display_name: str | None = None
    is_bot: bool


class BotInspectRequest(BaseModel):
    bot: str = Field(min_length=2, max_length=128)


class SendMessageRequest(BaseModel):
    bot: str = Field(min_length=2, max_length=128)
    text: str = Field(min_length=1, max_length=4096)


class RecentMessagesQuery(BaseModel):
    bot: str
    limit: int = Field(default=10, ge=1, le=50)


class WaitUpdateRequest(BaseModel):
    bot: str
    after_message_id: int | None = None
    watch_message_id: int | None = None
    previous_signature: str | None = None
    timeout_seconds: float = Field(default=30, ge=1, le=120)


class ClickButtonRequest(BaseModel):
    bot: str
    message_id: int
    text: str | None = Field(default=None, min_length=1, max_length=256)
    row: int | None = Field(default=None, ge=0, le=30)
    column: int | None = Field(default=None, ge=0, le=30)

    @model_validator(mode="after")
    def validate_selector(self) -> "ClickButtonRequest":
        has_text = self.text is not None
        has_position = self.row is not None and self.column is not None
        if has_text == has_position:
            raise ValueError("provide exactly one selector: text or row+column")
        return self


FlowAction = Literal[
    "send_message",
    "wait_message",
    "click_button",
    "wait_message_or_edit",
    "sleep",
    "assert_text",
]


class FlowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: FlowAction
    text: str | None = None
    row: int | None = Field(default=None, ge=0, le=30)
    column: int | None = Field(default=None, ge=0, le=30)
    timeout_seconds: float | None = Field(default=None, ge=0.1, le=120)
    seconds: float | None = Field(default=None, ge=0, le=60)
    contains_any: list[str] | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "FlowStep":
        if self.action == "send_message" and not self.text:
            raise ValueError("send_message requires text")
        if self.action == "click_button":
            has_text = bool(self.text)
            has_position = self.row is not None and self.column is not None
            if has_text == has_position:
                raise ValueError("click_button requires exactly one selector: text or row+column")
        if self.action == "sleep" and self.seconds is None:
            raise ValueError("sleep requires seconds")
        if self.action == "assert_text" and not self.contains_any:
            raise ValueError("assert_text requires contains_any")
        return self


class FlowCreate(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}$")
    name: str = Field(min_length=1, max_length=128)
    bot: str = Field(min_length=2, max_length=128)
    steps: list[FlowStep] = Field(min_length=1, max_length=50)


class FlowRecord(FlowCreate):
    created_at: str
    updated_at: str


class RunRecord(BaseModel):
    id: str
    task_type: str
    target: str | None = None
    priority: int
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict | list | str | int | float | bool | None = None
    error: dict | None = None
    created_at: str


class ApiResponse(BaseModel):
    ok: bool = True
    data: object | None = None
