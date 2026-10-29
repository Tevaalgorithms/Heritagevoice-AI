"""One trace ID per request: returned in a header, added to log lines and LangSmith metadata."""

import logging
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request, Response

TRACE_HEADER = "X-Trace-ID"
_VALID = re.compile(r"[A-Za-z0-9-]{8,64}")
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


def current_trace_id() -> str:
    return _trace_id.get()


def resolve_trace_id(incoming: str | None) -> str:
    """Accept a caller's ID only if it is a safe token; otherwise mint one."""
    return incoming if incoming and _VALID.fullmatch(incoming) else uuid4().hex


def langsmith_metadata() -> dict[str, str]:
    return {"trace_id": current_trace_id()}


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id()
        return True


def install_trace_logging() -> None:
    root = logging.getLogger()
    root.addFilter(TraceIdFilter())
    for handler in root.handlers:
        handler.addFilter(TraceIdFilter())


async def trace_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    token = _trace_id.set(resolve_trace_id(request.headers.get(TRACE_HEADER)))
    try:
        response = await call_next(request)
        response.headers[TRACE_HEADER] = current_trace_id()
        return response
    finally:
        _trace_id.reset(token)
