"""数据集分析与模型评价共用的 AI 流式编排。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from app.models.ai_setting import AISetting
from app.services.ai_service import chunk_text, classify_ai_error, openai_stream


@dataclass(frozen=True)
class AIStreamContract:
    start_status: str
    cached_done_status: str
    not_configured_message: str
    not_configured_reason_code: str
    not_configured_done_status: str
    success_done_status: str
    failure_message_prefix: str
    failure_done_status: str
    log_message: str
    start_event: str = "start"
    reasoning_event: str = "reasoning"
    delta_event: str = "delta"
    error_event: str = "error"
    done_event: str = "done"
    cached_source: str = "cached"
    ai_source: str = "ai"
    fallback_source: str = "fallback"


def replay_markdown(markdown: str, *, event: str = "delta") -> Iterable[tuple[str, dict[str, Any]]]:
    for part in chunk_text(str(markdown)):
        yield event, {"content": part}


def _fallback_events(
    markdown: str,
    *,
    reason_code: str,
    message: str,
    done_status: str,
    contract: AIStreamContract,
) -> Iterable[tuple[str, dict[str, Any]]]:
    yield contract.error_event, {"message": message, "reason_code": reason_code}
    yield from replay_markdown(markdown, event=contract.delta_event)
    yield contract.done_event, {"status": done_status, "source": contract.fallback_source}


def stream_ai_result(
    db: Any,
    *,
    cached_markdown: str | None,
    regenerate: bool,
    facts: dict[str, Any],
    prompt: list[dict[str, str]],
    fallback: Callable[[dict[str, Any]], str],
    save: Callable[[str, str, str | None], None],
    contract: AIStreamContract,
    logger: logging.Logger,
) -> Iterable[tuple[str, dict[str, Any]]]:
    yield contract.start_event, {"status": contract.start_status}

    if not regenerate and cached_markdown:
        yield from replay_markdown(cached_markdown, event=contract.delta_event)
        yield contract.done_event, {
            "status": contract.cached_done_status,
            "source": contract.cached_source,
        }
        return

    setting = db.get(AISetting, 1)
    if setting is None or not setting.enabled:
        markdown = fallback(facts)
        save(markdown, contract.fallback_source, None)
        yield from _fallback_events(
            markdown,
            reason_code=contract.not_configured_reason_code,
            message=contract.not_configured_message,
            done_status=contract.not_configured_done_status,
            contract=contract,
        )
        return

    try:
        parts: list[str] = []
        for kind, part in openai_stream(setting, prompt):
            if kind == "reasoning":
                yield contract.reasoning_event, {"content": part}
            else:
                parts.append(part)
                yield contract.delta_event, {"content": part}
        markdown = "".join(parts).strip()
        if not markdown:
            raise RuntimeError("empty AI response")
        save(markdown, contract.ai_source, setting.model)
        yield contract.done_event, {
            "status": contract.success_done_status,
            "source": contract.ai_source,
        }
    except Exception as exc:  # noqa: BLE001
        code, message = classify_ai_error(exc)
        logger.warning(contract.log_message, code)
        markdown = fallback(facts)
        save(markdown, contract.fallback_source, getattr(setting, "model", None))
        yield from _fallback_events(
            markdown,
            reason_code=code,
            message=f"{contract.failure_message_prefix}{message}",
            done_status=contract.failure_done_status,
            contract=contract,
        )
