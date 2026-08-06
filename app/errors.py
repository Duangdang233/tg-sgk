from __future__ import annotations


class TgSgkError(Exception):
    code = "TG_SGK_ERROR"
    status_code = 400

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(TgSgkError):
    code = "UNAUTHORIZED"
    status_code = 401


class TelegramNotConfiguredError(TgSgkError):
    code = "TELEGRAM_NOT_CONFIGURED"
    status_code = 503


class TelegramAuthorizationRequiredError(TgSgkError):
    code = "TELEGRAM_AUTHORIZATION_REQUIRED"
    status_code = 503


class TargetNotBotError(TgSgkError):
    code = "TARGET_IS_NOT_A_BOT"
    status_code = 403


class TargetNotFoundError(TgSgkError):
    code = "TARGET_NOT_FOUND"
    status_code = 404


class FlowNotFoundError(TgSgkError):
    code = "FLOW_NOT_FOUND"
    status_code = 404


class MessageNotFoundError(TgSgkError):
    code = "MESSAGE_NOT_FOUND"
    status_code = 404


class ButtonNotFoundError(TgSgkError):
    code = "BUTTON_NOT_FOUND"
    status_code = 404


class WaitTimeoutError(TgSgkError):
    code = "WAIT_TIMEOUT"
    status_code = 408
