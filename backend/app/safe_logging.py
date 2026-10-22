"""Sanitized error logging for paths that may handle clinical content."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from uuid import uuid4

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def error_status_code(error: BaseException) -> int | None:
    """Find an HTTP status on an exception chain without logging its message."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        for attr in ("code", "status_code"):
            value = getattr(current, attr, None)
            if isinstance(value, int) and 100 <= value <= 599:
                return value
        current = current.__cause__ or current.__context__
    return None


def _safe_error_category(error: BaseException | str) -> str:
    if not isinstance(error, BaseException):
        return "Error"
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        status = None
        for attr in ("code", "status_code"):
            value = getattr(current, attr, None)
            if isinstance(value, int) and 100 <= value <= 599:
                status = value
                break
        if status is not None:
            return f"{type(current).__name__}_HTTP_{status}"
        current = current.__cause__ or current.__context__
    return type(error).__name__


def set_request_id(value: str):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)

def log_safe_error(
    logger: logging.Logger,
    *,
    request_id: str | None,
    step: str,
    error: BaseException | str,
) -> None:
    """Log only a correlation ID, step, and error class; never tracebacks."""
    logger.error(
        "request_id=%s step=%s error_category=%s",
        request_id or _request_id.get() or str(uuid4()),
        step,
        _safe_error_category(error),
    )
