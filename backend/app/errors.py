"""One error type for the whole API: {"error": code, "message": text, "details": [...]}."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None, extra: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details, self.extra = details or [], extra or {}

    def body(self) -> dict:
        return {"error": self.code, "message": self.message, "details": self.details, **self.extra}


def bad(message: str, details: list | None = None, code: str = "invalid") -> ApiError:
    return ApiError(400, code, message, details)


def conflict(message: str, details: list | None = None, code: str = "conflict", extra: dict | None = None) -> ApiError:
    return ApiError(409, code, message, details, extra)


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", message)
