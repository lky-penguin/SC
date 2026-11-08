"""Server-Sent Events formatting and response helpers."""
from __future__ import annotations

import json
from collections.abc import Iterable

from fastapi.responses import StreamingResponse

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(events: Iterable[tuple[str, dict]]) -> StreamingResponse:
    return StreamingResponse(
        (format_sse_event(event, data) for event, data in events),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
